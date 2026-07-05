from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import sys
import time

import requests

from app.conversations.archive_sink import build_archive_sink_from_env
from app.integrations.meta_whatsapp.client import (
    MetaWhatsAppClient,
    MetaWhatsAppRequestError,
)


@dataclass(frozen=True)
class DeliveryRoute:
    name: str
    url_env: str
    transport_env: str
    default_transport: str = "internal_webhook"


EVENT_DELIVERY_ROUTES = {
    "handoff.requested": "handoff",
    "whatsapp.message.requested": "whatsapp_message",
    "otp.delivery.requested": "otp_delivery",
    "conversation.turn.archived": "conversation_archive",
}
DELIVERY_ROUTES = {
    "handoff": DeliveryRoute(
        name="handoff",
        url_env="HANDOFF_WEBHOOK_URL",
        transport_env="OUTBOX_HANDOFF_DELIVERY_TRANSPORT",
    ),
    "whatsapp_message": DeliveryRoute(
        name="whatsapp_message",
        url_env="WHATSAPP_MESSAGE_WEBHOOK_URL",
        transport_env="OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
    ),
    "otp_delivery": DeliveryRoute(
        name="otp_delivery",
        url_env="OTP_DELIVERY_WEBHOOK_URL",
        transport_env="OUTBOX_OTP_DELIVERY_TRANSPORT",
    ),
    "conversation_archive": DeliveryRoute(
        name="conversation_archive",
        url_env="",
        transport_env="OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT",
        default_transport="append_only_sink",
    ),
}
SUPPORTED_DELIVERY_TRANSPORTS = {
    "internal_webhook",
    "meta_whatsapp",
    "append_only_sink",
    "disabled",
}
META_WHATSAPP_ROUTES = {"whatsapp_message"}
MAX_ATTEMPTS = 5
RETRYABLE_HTTP_STATUS = {408, 409, 425, 429}
DEFAULT_PROCESSING_STALE_SECONDS = 300


class PermanentDeliveryError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch operational outbox events.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    if args.once == args.loop:
        parser.error("choose exactly one of --once or --loop")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")

    while True:
        processed = dispatch_one(database_url)
        if args.once:
            return 0
        if not processed:
            time.sleep(2)


def dispatch_one(database_url: str) -> bool:
    import psycopg
    from psycopg.rows import dict_row

    connect_timeout = _positive_int_env("DATABASE_CONNECT_TIMEOUT_SECONDS", 5)
    query_timeout = _positive_int_env("DATABASE_QUERY_TIMEOUT_SECONDS", 10)
    processing_stale_seconds = _positive_int_env(
        "OUTBOX_PROCESSING_STALE_SECONDS",
        DEFAULT_PROCESSING_STALE_SECONDS,
    )
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=connect_timeout,
        options=f"-c statement_timeout={query_timeout * 1000}",
    ) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM operational_outbox
                    WHERE (
                      status IN ('pending', 'retryable_failed')
                      AND available_at <= now()
                    ) OR (
                      status = 'processing'
                      AND (
                        locked_at IS NULL
                        OR locked_at < now() - (%s * INTERVAL '1 second')
                      )
                    )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    (processing_stale_seconds,),
                )
                event = cursor.fetchone()
                if event is None:
                    return False
                cursor.execute(
                    """
                    UPDATE operational_outbox
                    SET status = 'processing', attempt_count = attempt_count + 1,
                        locked_at = now()
                    WHERE id = %s
                    """,
                    (event["id"],),
                )

        try:
            delivery_result = deliver(event)
        except Exception as exc:
            attempts = int(event["attempt_count"]) + 1
            terminal = isinstance(exc, PermanentDeliveryError) or attempts >= MAX_ATTEMPTS
            error_code = (
                "permanent_delivery_failed"
                if isinstance(exc, PermanentDeliveryError)
                else "delivery_failed"
            )
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE operational_outbox
                        SET status = %s, last_error_code = %s,
                            available_at = %s, locked_at = NULL
                        WHERE id = %s
                        """,
                        (
                            "dead_letter" if terminal else "retryable_failed",
                            error_code,
                            datetime.now(UTC) + timedelta(seconds=min(300, 2**attempts)),
                            event["id"],
                        ),
                    )
            if terminal:
                emit_operational_event(
                    "outbox_dead_letter",
                    event_type=event["event_type"],
                    request_id=event["request_id"],
                    attempt_count=attempts,
                    error_code=error_code,
                )
        else:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE operational_outbox
                        SET status = 'delivered', processed_at = now(),
                            last_error_code = NULL, locked_at = NULL
                        WHERE id = %s
                        """,
                        (event["id"],),
                    )
                    _maybe_record_message_delivery(
                        cursor, event=event, result=delivery_result
                    )
    return True


@dataclass(frozen=True)
class DeliveryResult:
    """``meta_message_id`` is only set for a successful ``meta_whatsapp``
    send; used to correlate the delivery-status webhook back to the
    originating ``messages`` row (ponte WhatsApp<->console, compositor)."""

    meta_message_id: str | None = None


def _maybe_record_message_delivery(cursor, *, event: dict, result: "DeliveryResult") -> None:
    payload = event["payload_sanitized"]
    message_row_id = payload.get("message_row_id") if isinstance(payload, dict) else None
    if not message_row_id or not result.meta_message_id:
        return
    cursor.execute(
        """
        UPDATE messages
        SET meta_message_id = %s, delivery_status = 'sent'
        WHERE id = %s
        """,
        (result.meta_message_id, message_row_id),
    )


def deliver(event: dict) -> DeliveryResult:
    route = resolve_delivery_route(str(event["event_type"]))
    transport = resolve_delivery_transport(route)
    if transport == "disabled":
        raise PermanentDeliveryError(f"delivery route is disabled: {route.name}")
    if transport == "meta_whatsapp":
        return deliver_meta_whatsapp(event=event, route=route)
    if transport == "append_only_sink":
        deliver_conversation_archive(event=event)
        return DeliveryResult()
    deliver_internal_webhook(event=event, route=route)
    return DeliveryResult()


def deliver_conversation_archive(*, event: dict) -> None:
    sink = build_archive_sink_from_env()
    sink.append(
        idempotency_key=event["idempotency_key"],
        event_type=str(event["event_type"]),
        request_id=event["request_id"],
        payload=event["payload_sanitized"],
    )


def deliver_internal_webhook(*, event: dict, route: DeliveryRoute) -> None:
    url = os.getenv(route.url_env)
    if not url:
        raise RuntimeError(f"event delivery URL is not configured: {route.url_env}")
    secret = os.getenv("OUTBOX_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("OUTBOX_WEBHOOK_SECRET is not configured")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps(
        event["payload_sanitized"],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    response = requests.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": event["request_id"] or "",
            "X-Idempotency-Key": event["idempotency_key"],
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": f"sha256={signature}",
        },
        timeout=5,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = response.status_code
        if 400 <= status_code < 500 and status_code not in RETRYABLE_HTTP_STATUS:
            raise PermanentDeliveryError("permanent webhook rejection") from exc
        raise


def deliver_meta_whatsapp(*, event: dict, route: DeliveryRoute) -> DeliveryResult:
    if route.name not in META_WHATSAPP_ROUTES:
        raise PermanentDeliveryError(
            f"meta_whatsapp transport is not supported for route: {route.name}",
        )
    payload = event["payload_sanitized"]
    if not isinstance(payload, dict):
        raise PermanentDeliveryError("meta_whatsapp payload must be an object")
    recipient = _required_text(payload, "to")
    text = _required_text(payload, "text")
    # Modo-por-numero: "support" e a ponte WhatsApp<->console (numero de
    # suporte, atendimento humano); ausente/qualquer outro valor e o
    # comportamento de hoje (numero do bot/notificacao ao time). Mesma WABA,
    # mesmo access token -- so o phone_number_id muda entre numeros.
    phone_number_kind = payload.get("phone_number_kind")
    phone_number_id_env = (
        "META_SUPPORT_PHONE_NUMBER_ID"
        if phone_number_kind == "support"
        else "META_WHATSAPP_PHONE_NUMBER_ID"
    )
    client = MetaWhatsAppClient(
        access_token=_required_env("META_WHATSAPP_ACCESS_TOKEN"),
        phone_number_id=_required_env(phone_number_id_env),
        graph_api_version=os.getenv("META_WHATSAPP_GRAPH_API_VERSION", "v25.0"),
        timeout_seconds=_positive_int_env("META_WHATSAPP_REQUEST_TIMEOUT_SECONDS", 5),
    )
    try:
        result = client.send_text(to=recipient, text=text)
    except MetaWhatsAppRequestError as exc:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            if exc.status_code not in RETRYABLE_HTTP_STATUS:
                raise PermanentDeliveryError("permanent meta whatsapp rejection") from exc
        raise
    return DeliveryResult(meta_message_id=result.message_id)


def resolve_delivery_route(event_type: str) -> DeliveryRoute:
    route_name = EVENT_DELIVERY_ROUTES.get(event_type)
    if route_name is None:
        raise PermanentDeliveryError(f"unsupported event type: {event_type}")
    return DELIVERY_ROUTES[route_name]


def resolve_delivery_transport(route: DeliveryRoute) -> str:
    transport = os.getenv(route.transport_env, route.default_transport).strip().lower()
    transport = transport or route.default_transport
    if transport not in SUPPORTED_DELIVERY_TRANSPORTS:
        raise PermanentDeliveryError(f"unsupported delivery transport: {transport}")
    return transport


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    raise RuntimeError(f"{name} is not configured")


def _required_text(payload: dict, name: str) -> str:
    value = payload.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise PermanentDeliveryError(f"meta_whatsapp payload field is required: {name}")


def emit_operational_event(event: str, **fields: object) -> None:
    print(
        json.dumps({"event": event, **fields}, ensure_ascii=True, default=str),
        file=sys.stderr,
    )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
