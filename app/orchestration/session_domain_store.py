"""Sticky domain memory for conversational channels.

Remembers which domain a conversation chose (for example ``vendas``) so that
follow-up messages that are not, by themselves, keyword-routable stay in that
domain instead of falling back to the menu on every turn.

This module owns only the CONTRACT and an ephemeral in-process default. The
durable, multi-process implementation (PostgreSQL, keyed by the sanitized session
id, with TTL and privacy guarantees) belongs to the persistence frente and should
implement the same :class:`SessionDomainStore` protocol.

Privacy: the key is always the already-sanitized session id (a hash such as
``whatsapp:meta:<digest>``). Never store a raw ``wa_id``, phone number, or message
text here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol, runtime_checkable


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
