from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import sys
import time

import requests


EVENT_URLS = {
    "handoff.requested": "HANDOFF_WEBHOOK_URL",
    "whatsapp.message.requested": "WHATSAPP_MESSAGE_WEBHOOK_URL",
    "otp.delivery.requested": "OTP_DELIVERY_WEBHOOK_URL",
}
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
            deliver(event)
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
    return True


def deliver(event: dict) -> None:
    env_name = EVENT_URLS.get(event["event_type"])
    url = os.getenv(env_name or "")
    if not url:
        raise RuntimeError("event delivery URL is not configured")
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
