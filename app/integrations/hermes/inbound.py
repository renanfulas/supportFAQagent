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


@dataclass(frozen=True)
class HermesInboundMessage:
    message_id: str
    from_wa_id: str
    chat_id: str
    text: str


def parse_hermes_inbound(payload: dict[str, Any]) -> list[HermesInboundMessage]:
    """Parse the bridge's native inbound event(s).

    Accepts either a single event object (the bridge ``event`` shape) or a batch
    under ``messages``/``events``. Group chats and empty/media-only messages are
    ignored in the pilot.
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
        parsed.append(
            HermesInboundMessage(
                message_id=message_id,
                from_wa_id=from_wa_id,
                chat_id=chat_id,
                text=text,
            )
        )
    return parsed
