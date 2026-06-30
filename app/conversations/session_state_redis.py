"""Redis backend for the hot-tier session state (layered-persistence Nível 1).

Operational tier: state survives an app restart (not a Redis crash) within the TTL,
and is consistent across uvicorn workers. Non-authoritative — the source of truth
stays the Postgres write-through, so every path is **fail-open**: a Redis problem
degrades to "no state", never breaks `/chat`.

The redis client is injectable (like ``S3ObjectSink`` accepts ``client=``) so tests
run without the optional ``redis`` dependency. Key: ``sess:{domain}:{channel}:{hash}``.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from typing import Any, Callable

from app.conversations.session_state import SessionState


logger = logging.getLogger(__name__)


def _key(domain: str, channel: str, session_hash: str) -> str:
    return f"sess:{domain}:{channel}:{session_hash}"


class RedisSessionStateStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(
        cls, getenv: Callable[[str, str], str] = os.getenv
    ) -> "RedisSessionStateStore":
        url = (getenv("SESSION_STATE_REDIS_URL", "") or "").strip()
        if not url:
            raise ValueError(
                "SESSION_STATE_REDIS_URL is required for SESSION_STATE_BACKEND=redis"
            )
        try:
            import redis  # optional extra: pip install '.[redis]'
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise RuntimeError(
                "SESSION_STATE_BACKEND=redis requires the 'redis' extra: pip install '.[redis]'"
            ) from exc
        return cls(redis.Redis.from_url(url))

    def get(
        self, *, domain: str, channel: str, session_hash: str
    ) -> SessionState | None:
        try:
            raw = self._client.get(_key(domain, channel, session_hash))
        except Exception:  # noqa: BLE001 - fail-open: Redis down must not break /chat.
            logger.debug("session_state_redis_get_failed", exc_info=False)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            return SessionState(**json.loads(raw))
        except Exception:  # noqa: BLE001 - corrupt/old value degrades to no state.
            return None

    def put(
        self,
        *,
        domain: str,
        channel: str,
        session_hash: str,
        state: SessionState,
        ttl_seconds: int,
    ) -> None:
        try:
            payload = json.dumps(asdict(state))
            key = _key(domain, channel, session_hash)
            if ttl_seconds and ttl_seconds > 0:
                self._client.set(key, payload, ex=ttl_seconds)
            else:
                self._client.set(key, payload)
        except Exception:  # noqa: BLE001 - fail-open: hot state is non-authoritative.
            logger.debug("session_state_redis_put_failed", exc_info=False)

    def clear(self, *, domain: str, channel: str, session_hash: str) -> None:
        try:
            self._client.delete(_key(domain, channel, session_hash))
        except Exception:  # noqa: BLE001 - fail-open.
            logger.debug("session_state_redis_clear_failed", exc_info=False)
