from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac

from app.db.runtime import DatabaseRuntime


MAX_SKEW_SECONDS = 300
PROCESSING_STALE_SECONDS = 300

CLAIMED = "claimed"
DUPLICATE = "duplicate"
IN_PROGRESS = "in_progress"
PAYLOAD_CONFLICT = "payload_conflict"


def verify_signature(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
    now: int | None = None,
) -> bool:
    if not secret or not timestamp or not signature or not signature.startswith("sha256="):
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else int(datetime.now(UTC).timestamp())
    if abs(current - sent_at) > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def idempotency_hash(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClaimResult:
    status: str
    attempt_count: int


class WebhookIngressRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def claim(
        self,
        *,
        event_type: str,
        idempotency_key: str,
        request_id: str | None,
        body_hash: str,
    ) -> ClaimResult:
        key_hash = idempotency_hash(idempotency_key)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_type, payload_hash, status, attempt_count,
                           updated_at < now() - INTERVAL '5 minutes'
                    FROM webhook_ingress_receipts
                    WHERE idempotency_key_hash = %s
                    FOR UPDATE
                    """,
                    (key_hash,),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        INSERT INTO webhook_ingress_receipts (
                          idempotency_key_hash, event_type, request_id, payload_hash
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (key_hash, event_type, request_id, body_hash),
                    )
                    return ClaimResult(CLAIMED, 1)
                if row[0] != event_type or row[1] != body_hash:
                    return ClaimResult(PAYLOAD_CONFLICT, int(row[3]))
                if row[2] == "delivered":
                    return ClaimResult(DUPLICATE, int(row[3]))
                if row[2] == "processing" and not row[4]:
                    return ClaimResult(IN_PROGRESS, int(row[3]))
                cursor.execute(
                    """
                    UPDATE webhook_ingress_receipts
                    SET status = 'processing', attempt_count = attempt_count + 1,
                        last_error_code = NULL, updated_at = now()
                    WHERE idempotency_key_hash = %s
                    RETURNING attempt_count
                    """,
                    (key_hash,),
                )
                return ClaimResult(CLAIMED, int(cursor.fetchone()[0]))

    def mark_delivered(self, idempotency_key: str) -> None:
        self._mark(idempotency_key, status="delivered", error_code=None)

    def mark_failed(self, idempotency_key: str, error_code: str) -> None:
        self._mark(idempotency_key, status="retryable_failed", error_code=error_code)

    def _mark(self, idempotency_key: str, *, status: str, error_code: str | None) -> None:
        key_hash = idempotency_hash(idempotency_key)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE webhook_ingress_receipts
                    SET status = %s, last_error_code = %s, updated_at = now(),
                        delivered_at = CASE WHEN %s = 'delivered' THEN now() ELSE delivered_at END
                    WHERE idempotency_key_hash = %s
                    """,
                    (status, error_code, status, key_hash),
                )
