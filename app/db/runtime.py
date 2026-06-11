from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import Settings
from app.core.errors import DatabaseUnavailableError


class DatabaseRuntime:
    """Owns the process-wide PostgreSQL pool and explicit transactions."""

    def __init__(self, settings: Settings, *, pool: Any | None = None) -> None:
        self.settings = settings
        self._pool = pool

    @property
    def enabled(self) -> bool:
        return (
            self.settings.persistence_backend == "postgres"
            or self.settings.web_auth_storage_backend == "postgres"
        )

    def open(self) -> None:
        if not self.enabled or self._pool is not None:
            return
        try:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                conninfo=self.settings.database_url or "",
                min_size=self.settings.database_pool_min_size,
                max_size=self.settings.database_pool_max_size,
                timeout=self.settings.database_connect_timeout_seconds,
                kwargs={
                    "connect_timeout": self.settings.database_connect_timeout_seconds,
                    "options": (
                        f"-c statement_timeout="
                        f"{self.settings.database_query_timeout_seconds * 1000}"
                    ),
                },
                open=True,
            )
            self._pool.wait(timeout=self.settings.database_connect_timeout_seconds)
        except Exception as exc:
            self._pool = None
            raise DatabaseUnavailableError("database pool unavailable") from exc

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        if not self.enabled:
            raise DatabaseUnavailableError("persistence backend is disabled")
        if self._pool is None:
            self.open()
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    yield connection
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            raise DatabaseUnavailableError("database transaction failed") from exc

    def healthcheck(self) -> bool:
        try:
            with self.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return cursor.fetchone()[0] == 1
        except DatabaseUnavailableError:
            return False
