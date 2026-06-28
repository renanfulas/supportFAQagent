"""Sticky domain memory for conversational channels.

Remembers which domain a conversation chose (for example ``vendas``) so that
follow-up messages that are not, by themselves, keyword-routable stay in that
domain instead of falling back to the menu on every turn.

This module owns the CONTRACT, an ephemeral in-process default
(:class:`InMemorySessionDomainStore`) and the durable, multi-process
implementation (:class:`PgSessionDomainStore`, PostgreSQL, keyed by the sanitized
session id, with TTL and privacy guarantees). :func:`build_session_domain_store`
picks between them from config, dark by default.

Privacy: the key is always the already-sanitized session id (a hash such as
``whatsapp:meta:<digest>``). Never store a raw ``wa_id``, phone number, or message
text here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event

if TYPE_CHECKING:
    from app.db.runtime import DatabaseRuntime


logger = logging.getLogger(__name__)


@runtime_checkable
class SessionDomainStore(Protocol):
    """Read/write the domain a session is currently bound to."""

    def get(self, session_id: str) -> str | None:
        """Return the bound domain for ``session_id`` or ``None`` if absent/expired."""

    def set(self, session_id: str, domain: str) -> None:
        """Bind ``session_id`` to ``domain`` (refreshing any TTL)."""

    def clear(self, session_id: str) -> None:
        """Forget the binding for ``session_id`` (used by the reset trigger)."""


@dataclass
class InMemorySessionDomainStore:
    """Ephemeral in-process default.

    Good for local/dev and single-process runs. It does NOT survive restarts and is
    NOT shared across workers/replicas; production stickiness needs the durable
    implementation from the persistence frente.
    """

    ttl_seconds: int = 3600
    _entries: dict[str, tuple[str, float]] = field(default_factory=dict)

    def get(self, session_id: str) -> str | None:
        entry = self._entries.get(session_id)
        if entry is None:
            return None
        domain, expires_at = entry
        if self.ttl_seconds > 0 and time.monotonic() >= expires_at:
            self._entries.pop(session_id, None)
            return None
        return domain

    def set(self, session_id: str, domain: str) -> None:
        self._entries[session_id] = (domain, time.monotonic() + self.ttl_seconds)

    def clear(self, session_id: str) -> None:
        self._entries.pop(session_id, None)


class PgSessionDomainStore:
    """Durable, cross-process :class:`SessionDomainStore` backed by PostgreSQL.

    Mirrors :class:`InMemorySessionDomainStore` but survives restarts and is shared
    across workers/replicas, so WhatsApp stickiness stays correct in production.
    The key is the already-sanitized session id (a digest such as
    ``whatsapp:hermes:<digest>``) — never a raw ``wa_id``, phone, or message text.
    Fail-open: any persistence error degrades stickiness to "show the menu" rather
    than breaking the channel, mirroring the reader in ``summary_reader``.
    """

    def __init__(self, runtime: "DatabaseRuntime", *, ttl_seconds: int = 3600) -> None:
        self.runtime = runtime
        self.ttl_seconds = ttl_seconds

    def get(self, session_id: str) -> str | None:
        if not session_id or not self.runtime.persistence_enabled:
            return None
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT domain
                        FROM session_domain_binding
                        WHERE session_id_hash = %s
                          AND (expires_at IS NULL OR expires_at > now())
                        """,
                        (session_id,),
                    )
                    row = cursor.fetchone()
        except DatabaseUnavailableError:
            log_event(
                logger,
                "session_domain_store_unavailable",
                operation="get",
                error_code="database_unavailable",
            )
            return None
        return str(row[0]) if row else None

    def set(self, session_id: str, domain: str) -> None:
        if not session_id or not domain or not self.runtime.persistence_enabled:
            return
        if self.ttl_seconds and self.ttl_seconds > 0:
            expires_sql = "now() + make_interval(secs => %s)"
            params: tuple = (session_id, domain, self.ttl_seconds)
        else:
            expires_sql = "NULL"
            params = (session_id, domain)
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO session_domain_binding
                            (session_id_hash, domain, updated_at, expires_at)
                        VALUES (%s, %s, now(), {expires_sql})
                        ON CONFLICT (session_id_hash) DO UPDATE
                            SET domain = EXCLUDED.domain,
                                updated_at = EXCLUDED.updated_at,
                                expires_at = EXCLUDED.expires_at
                        """,
                        params,
                    )
        except DatabaseUnavailableError:
            log_event(
                logger,
                "session_domain_store_unavailable",
                operation="set",
                error_code="database_unavailable",
            )

    def clear(self, session_id: str) -> None:
        if not session_id or not self.runtime.persistence_enabled:
            return
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM session_domain_binding WHERE session_id_hash = %s",
                        (session_id,),
                    )
        except DatabaseUnavailableError:
            log_event(
                logger,
                "session_domain_store_unavailable",
                operation="clear",
                error_code="database_unavailable",
            )


def build_session_domain_store(
    runtime: "DatabaseRuntime", *, ttl_seconds: int = 3600
) -> SessionDomainStore:
    """Return the durable Postgres store when enabled, else the in-memory default.

    Dark by default: only ``SESSION_DOMAIN_STORE_BACKEND=postgres`` (with
    persistence on) swaps in :class:`PgSessionDomainStore`. Any other value — or
    persistence disabled — keeps the ephemeral :class:`InMemorySessionDomainStore`,
    so behavior is unchanged until the flag is consciously turned on.
    """
    backend = getattr(runtime.settings, "session_domain_store_backend", "memory")
    if backend == "postgres" and runtime.persistence_enabled:
        return PgSessionDomainStore(runtime, ttl_seconds=ttl_seconds)
    return InMemorySessionDomainStore(ttl_seconds=ttl_seconds)
