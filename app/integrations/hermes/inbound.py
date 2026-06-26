"""Inbound message contract for the temporary Hermes chat bridge.

PROPOSED contract: when Hermes receives a WhatsApp message it forwards a signed
POST to our webhook with this JSON shape. The exact field names must be confirmed
with the Hermes service owner (Alexandre) before activation; the parser is
deliberately small and tolerant so it is cheap to adjust.

    {
      "messages": [
        {"from": "<wa_id>", "id": "<message_id>", "type": "text",
         "text": "<body>"}
      ]
    }

Only text messages are handled; anything else is ignored (no media in the pilot).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import threading
from typing import Any


MAX_SKEW_SECONDS = 300


def verify_hermes_signature(
    *,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    secret: str,
    now: int | None = None,
) -> bool:
    """Verify an inbound Hermes request.

    Symmetric with the outbound OTP/chat signing: ``HMAC-SHA256(secret, body)`` as a
    hex digest in ``X-Webhook-Signature`` plus a fresh ``X-Webhook-Timestamp`` to
    bound replay. The timestamp is not part of the HMAC, matching ``deliver_otp``.
    """
    if not secret or not signature or not timestamp:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else int(datetime.now(UTC).timestamp())
    if abs(current - sent_at) > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class HermesReplayGuard:
    """Reject verbatim replays of an already-seen inbound signature.

    The inbound HMAC covers only the request body, so a captured valid request can be
    replayed unchanged for up to ``MAX_SKEW_SECONDS`` and would otherwise be processed
    again (duplicate outbound sends, duplicate LLM cost). Remembering recently-seen
    signatures closes that window without changing the wire contract with the bridge.

    Process-local and best-effort: it lives on ``app.state`` for one worker. A durable,
    cross-process nonce store is a follow-up if the channel ever scales horizontally.
    """

    def __init__(self, ttl_seconds: int = MAX_SKEW_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_remember(self, signature: str, *, now: float | None = None) -> bool:
        """Return True when the signature is fresh; False when it is a replay."""
        if not signature:
            return False
        current = now if now is not None else datetime.now(UTC).timestamp()
        with self._lock:
            self._prune(current)
            if signature in self._seen:
                return False
            self._seen[signature] = current + self._ttl
            return True

    def _prune(self, current: float) -> None:
        expired = [sig for sig, expiry in self._seen.items() if expiry <= current]
        for sig in expired:
            del self._seen[sig]


@dataclass(frozen=True)
class HermesInboundMessage:
    message_id: str
    from_wa_id: str
    chat_id: str
    text: str


def parse_hermes_inbound(
    payload: dict[str, Any],
    *,
    max_text_chars: int | None = None,
) -> list[HermesInboundMessage]:
    """Parse the bridge's native inbound event(s).

    Accepts either a single event object (the bridge ``event`` shape) or a batch
    under ``messages``/``events``. Group chats and empty/media-only messages are
    ignored in the pilot.

    ``max_text_chars`` bounds each message body before it ever reaches the LLM, so a
    single oversized message cannot be used to inflate token cost or stuff the prompt.
    """
    raw = payload.get("messages")
    if not isinstance(raw, list):
        raw = payload.get("events")
    if not isinstance(raw, list):
        raw = [payload]

    parsed: list[HermesInboundMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("isGroup"):
            continue
        chat_id = str(item.get("chatId", "")).strip()
        from_wa_id = str(item.get("senderId") or chat_id).strip()
        message_id = str(item.get("messageId", "")).strip()
        text = str(item.get("body", "")).strip()
        if not chat_id or not message_id or not text:
            continue
        if max_text_chars is not None and len(text) > max_text_chars:
            text = text[:max_text_chars]
        parsed.append(
            HermesInboundMessage(
                message_id=message_id,
                from_wa_id=from_wa_id,
                chat_id=chat_id,
                text=text,
            )
        )
    return parsed
