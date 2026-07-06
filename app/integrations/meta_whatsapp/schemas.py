from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetaInboundTextMessage:
    message_id: str
    from_wa_id: str
    timestamp: str | None
    text: str
    # ``value.metadata.phone_number_id`` -- which of our numbers this arrived
    # on (bot vs. support). None for payloads that predate this field.
    phone_number_id: str | None = None


@dataclass(frozen=True)
class MetaMessageStatus:
    message_id: str
    status: str
    timestamp: str | None
    recipient_id: str | None
    phone_number_id: str | None = None


@dataclass(frozen=True)
class MetaWebhookPayload:
    messages: list[MetaInboundTextMessage]
    statuses: list[MetaMessageStatus]


@dataclass(frozen=True)
class MetaSendResult:
    message_id: str
    contact_wa_id: str | None = None


def parse_webhook_payload(payload: dict[str, Any]) -> MetaWebhookPayload:
    messages: list[MetaInboundTextMessage] = []
    statuses: list[MetaMessageStatus] = []
    for entry in _iter_dicts(payload.get("entry")):
        for change in _iter_dicts(entry.get("changes")):
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = (
                metadata.get("phone_number_id")
                if isinstance(metadata, dict)
                and isinstance(metadata.get("phone_number_id"), str)
                else None
            )
            messages.extend(
                _parse_messages(value.get("messages"), phone_number_id=phone_number_id)
            )
            statuses.extend(
                _parse_statuses(value.get("statuses"), phone_number_id=phone_number_id)
            )
    return MetaWebhookPayload(messages=messages, statuses=statuses)


def _parse_messages(
    raw_messages: object, *, phone_number_id: str | None
) -> list[MetaInboundTextMessage]:
    parsed: list[MetaInboundTextMessage] = []
    for item in _iter_dicts(raw_messages):
        text = item.get("text")
        body = text.get("body") if isinstance(text, dict) else None
        if item.get("type") != "text" or not isinstance(body, str) or not body.strip():
            continue
        message_id = item.get("id")
        from_wa_id = item.get("from")
        if not isinstance(message_id, str) or not isinstance(from_wa_id, str):
            continue
        timestamp = item.get("timestamp")
        parsed.append(
            MetaInboundTextMessage(
                message_id=message_id,
                from_wa_id=from_wa_id,
                timestamp=timestamp if isinstance(timestamp, str) else None,
                text=body,
                phone_number_id=phone_number_id,
            )
        )
    return parsed


def _parse_statuses(
    raw_statuses: object, *, phone_number_id: str | None
) -> list[MetaMessageStatus]:
    parsed: list[MetaMessageStatus] = []
    for item in _iter_dicts(raw_statuses):
        message_id = item.get("id")
        status = item.get("status")
        if not isinstance(message_id, str) or not isinstance(status, str):
            continue
        timestamp = item.get("timestamp")
        recipient_id = item.get("recipient_id")
        parsed.append(
            MetaMessageStatus(
                message_id=message_id,
                status=status,
                timestamp=timestamp if isinstance(timestamp, str) else None,
                recipient_id=recipient_id if isinstance(recipient_id, str) else None,
                phone_number_id=phone_number_id,
            )
        )
    return parsed


def _iter_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
