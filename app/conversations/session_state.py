"""Hot-tier session state seam (layered-persistence plan, fatia/Fase 1).

Mirrors the philosophy of ``ConversationArchiveSink``: a stable interface with a
swappable implementation and a safe default. The state is the *non-authoritative*
hot tier — the source of truth stays in Postgres (decision A). A Redis backend
drops in behind ``SESSION_STATE_BACKEND=redis`` in a later slice (Nível 1) without
touching callers.

Privacy: keyed by ``(domain, channel, session_hash)`` — never a raw ``session_id``
nor free PII.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


SUPPORTED_SESSION_STATE_BACKENDS = {"memory", "redis"}
DEFAULT_SESSION_STATE_TTL_SECONDS = 2700  # 45 min hot window


@dataclass(frozen=True)
class SessionState:
    """Sanitized hot-tier state for a session. No raw session_id, no free PII."""

    state: str
    domain: str
    confidence: float
    updated_at: float
    turn_id: str | None = None
    redaction_version: str | None = None


@runtime_checkable
class SessionStateStore(Protocol):
    def get(
        self, *, domain: str, channel: str, session_hash: str
    ) -> SessionState | None: ...

    def put(
        self,
        *,
        domain: str,
        channel: str,
        session_hash: str,
        state: SessionState,
        ttl_seconds: int,
    ) -> None: ...

    def clear(self, *, domain: str, channel: str, session_hash: str) -> None: ...


def _key(domain: str, channel: str, session_hash: str) -> str:
    return f"{domain}::{channel}::{session_hash}"


class InMemorySessionStateStore:
    """Single-process store with wall-clock TTL. Local/CI/test default; mirrors the
    role of ``AppendOnlyFileSink``.

    NOT consistent across uvicorn workers and lost on restart — production
    multi-worker needs the Redis backend (Nível 1). This is fine because the hot
    tier is non-authoritative: the truth is the Postgres write-through.
    """

    def __init__(self, *, time_fn: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[str, tuple[float | None, SessionState]] = {}
        self._lock = threading.Lock()
        self._time_fn = time_fn

    def get(
        self, *, domain: str, channel: str, session_hash: str
    ) -> SessionState | None:
        key = _key(domain, channel, session_hash)
        now = self._time_fn()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, state = entry
            if expires_at is not None and now >= expires_at:
                self._data.pop(key, None)
                return None
            return state

    def put(
        self,
        *,
        domain: str,
        channel: str,
        session_hash: str,
        state: SessionState,
        ttl_seconds: int,
    ) -> None:
        key = _key(domain, channel, session_hash)
        expires_at = self._time_fn() + ttl_seconds if ttl_seconds > 0 else None
        with self._lock:
            self._data[key] = (expires_at, state)

    def clear(self, *, domain: str, channel: str, session_hash: str) -> None:
        key = _key(domain, channel, session_hash)
        with self._lock:
            self._data.pop(key, None)


def build_session_state_store_from_env(
    getenv: Callable[[str, str], str] = os.getenv,
) -> SessionStateStore:
    backend = (getenv("SESSION_STATE_BACKEND", "memory") or "memory").strip().lower()
    if backend not in SUPPORTED_SESSION_STATE_BACKENDS:
        raise ValueError(f"unsupported session state backend: {backend}")
    if backend == "memory":
        return InMemorySessionStateStore()
    # backend == "redis": RedisSessionStateStore is the next slice (Nível 1).
    raise NotImplementedError(
        "SESSION_STATE_BACKEND=redis requires RedisSessionStateStore (Nível 1, not yet implemented)"
    )
