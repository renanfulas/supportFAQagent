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
    def pool_enabled(self) -> bool:
        return (
            self.persistence_enabled
            or self.web_auth_enabled
            or self.ingress_enabled
            or self.retrieval_enabled
        )

    @property
    def enabled(self) -> bool:
        """Compatibility alias for code that only needs the shared pool."""
        return self.pool_enabled

    @property
    def persistence_enabled(self) -> bool:
        return self.settings.persistence_backend == "postgres"

    @property
    def web_auth_enabled(self) -> bool:
        return self.settings.web_auth_storage_backend == "postgres"

    @property
    def ingress_enabled(self) -> bool:
        return bool(getattr(self.settings, "enable_outbox_ingress", False))

    @property
    def retrieval_enabled(self) -> bool:
        return getattr(self.settings, "retrieval_backend", "lexical") == "pgvector"

    def open(self) -> None:
        if not self.pool_enabled or self._pool is not None:
            return
        pool = None
        try:
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
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
            pool.wait(timeout=self.settings.database_connect_timeout_seconds)
            self._pool = pool
        except Exception as exc:
            if pool is not None:
                pool.close()
            self._pool = None
            raise DatabaseUnavailableError("database pool unavailable") from exc

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        if not self.pool_enabled:
            raise DatabaseUnavailableError("database pool is disabled")
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
