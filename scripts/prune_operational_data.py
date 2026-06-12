from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from typing import Any


DEFAULT_CONVERSATION_RETENTION_DAYS = 60
DEFAULT_OTP_RETENTION_DAYS = 7
DEFAULT_OUTBOX_DELIVERED_RETENTION_DAYS = 30
DEFAULT_WEBHOOK_RECEIPT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 1000
DEFAULT_MAX_BATCHES = 10
DEFAULT_QUERY_TIMEOUT_SECONDS = 60

MAX_BATCH_SIZE = 5000
MAX_BATCHES = 50
MAX_ROWS_PER_TARGET_PER_RUN = 50_000


@dataclass(frozen=True)
class PruneResult:
    counts: dict[str, int]
    batches_run: int
    limit_reached: bool


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune expired operational data.")
    parser.add_argument(
        "--conversation-days",
        type=int,
        default=int(
            os.getenv(
                "CONVERSATION_RETENTION_DAYS",
                str(DEFAULT_CONVERSATION_RETENTION_DAYS),
            )
        ),
    )
    parser.add_argument(
        "--otp-days",
        type=int,
        default=int(os.getenv("OTP_RETENTION_DAYS", str(DEFAULT_OTP_RETENTION_DAYS))),
    )
    parser.add_argument(
        "--outbox-delivered-days",
        type=int,
        default=int(
            os.getenv(
                "OUTBOX_DELIVERED_RETENTION_DAYS",
                str(DEFAULT_OUTBOX_DELIVERED_RETENTION_DAYS),
            )
        ),
    )
    parser.add_argument(
        "--receipt-days",
        type=int,
        default=int(
            os.getenv(
                "WEBHOOK_RECEIPT_RETENTION_DAYS",
                str(DEFAULT_WEBHOOK_RECEIPT_RETENTION_DAYS),
            )
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("RETENTION_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))),
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=int(os.getenv("RETENTION_MAX_BATCHES", str(DEFAULT_MAX_BATCHES))),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    try:
        _validate_prune_limits(
            conversation_days=args.conversation_days,
            otp_days=args.otp_days,
            outbox_delivered_days=args.outbox_delivered_days,
            receipt_days=args.receipt_days,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    except ValueError as exc:
        parser.error(str(exc))

    import psycopg

    connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5"))
    query_timeout_seconds = int(
        os.getenv("RETENTION_QUERY_TIMEOUT_SECONDS", str(DEFAULT_QUERY_TIMEOUT_SECONDS))
    )
    if connect_timeout < 1 or query_timeout_seconds < 1:
        parser.error("database and retention query timeouts must be positive")
    with psycopg.connect(
        database_url,
        connect_timeout=connect_timeout,
        options=f"-c statement_timeout={query_timeout_seconds * 1000}",
    ) as connection:
        result = prune_operational_data(
            connection,
            conversation_days=args.conversation_days,
            otp_days=args.otp_days,
            outbox_delivered_days=args.outbox_delivered_days,
            receipt_days=args.receipt_days,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
            dry_run=args.dry_run,
        )
    print(
        f"{'would_prune' if args.dry_run else 'pruned'} "
        + " ".join(f"{name}={count}" for name, count in result.counts.items())
        + f" batches_run={result.batches_run}"
        + f" limit_reached={str(result.limit_reached).lower()}"
    )
    return 0


def prune_operational_data(
    connection: Any,
    *,
    conversation_days: int,
    otp_days: int,
    outbox_delivered_days: int,
    receipt_days: int,
    batch_size: int,
    max_batches: int,
    dry_run: bool,
) -> PruneResult:
    _validate_prune_limits(
        conversation_days=conversation_days,
        otp_days=otp_days,
        outbox_delivered_days=outbox_delivered_days,
        receipt_days=receipt_days,
        batch_size=batch_size,
        max_batches=max_batches,
    )
    if dry_run:
        candidate_limit = batch_size * max_batches
        with connection.transaction():
            with connection.cursor() as cursor:
                counts = prune_batch(
                    cursor,
                    conversation_days=conversation_days,
                    otp_days=otp_days,
                    outbox_delivered_days=outbox_delivered_days,
                    receipt_days=receipt_days,
                    batch_size=candidate_limit,
                    dry_run=True,
                )
        return PruneResult(
            counts=counts,
            batches_run=0,
            limit_reached=any(count >= candidate_limit for count in counts.values()),
        )

    totals: dict[str, int] = {}
    for batch_number in range(1, max_batches + 1):
        with connection.transaction():
            with connection.cursor() as cursor:
                batch_counts = prune_batch(
                    cursor,
                    conversation_days=conversation_days,
                    otp_days=otp_days,
                    outbox_delivered_days=outbox_delivered_days,
                    receipt_days=receipt_days,
                    batch_size=batch_size,
                    dry_run=False,
                )
        for name, count in batch_counts.items():
            totals[name] = totals.get(name, 0) + count

        more_may_remain = any(count >= batch_size for count in batch_counts.values())
        if not more_may_remain:
            return PruneResult(
                counts=totals,
                batches_run=batch_number,
                limit_reached=False,
            )

    return PruneResult(
        counts=totals,
        batches_run=max_batches,
        limit_reached=more_may_remain,
    )


def _validate_prune_limits(
    *,
    conversation_days: int,
    otp_days: int,
    outbox_delivered_days: int,
    receipt_days: int,
    batch_size: int,
    max_batches: int,
) -> None:
    retention_days = (
        conversation_days,
        otp_days,
        outbox_delivered_days,
        receipt_days,
    )
    if any(days < 1 for days in retention_days):
        raise ValueError("retention days must be positive")
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch size must be between 1 and {MAX_BATCH_SIZE}")
    if max_batches < 1 or max_batches > MAX_BATCHES:
        raise ValueError(f"max batches must be between 1 and {MAX_BATCHES}")
    if batch_size * max_batches > MAX_ROWS_PER_TARGET_PER_RUN:
        raise ValueError(
            "batch size multiplied by max batches exceeds the per-target safety limit"
        )


def prune_batch(
    cursor: Any,
    *,
    conversation_days: int,
    otp_days: int,
    outbox_delivered_days: int,
    receipt_days: int,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    # Feedback must be pruned before audits; the audit predicate preserves every
    # remaining matched feedback link even when a run stops between batches.
    targets = [
        (
            "messages",
            "messages",
            "id",
            "created_at < now() - (%s * INTERVAL '1 day')",
            conversation_days,
        ),
        (
            "conversations",
            "conversations",
            "id",
            """
            COALESCE(last_message_at, updated_at, created_at)
              < now() - (%s * INTERVAL '1 day')
            AND NOT EXISTS (
              SELECT 1 FROM messages WHERE messages.conversation_id = conversations.id
            )
            """,
            conversation_days,
        ),
        (
            "feedback",
            "feedback",
            "id",
            "created_at < now() - (%s * INTERVAL '1 day')",
            conversation_days,
        ),
        (
            "chat_audits",
            "chat_audits",
            "id",
            """
            created_at < now() - (%s * INTERVAL '1 day')
            AND NOT EXISTS (
              SELECT 1
              FROM feedback
              WHERE feedback.chat_audit_id = chat_audits.id
            )
            """,
            conversation_days,
        ),
        (
            "otp_challenges",
            "otp_challenges",
            "id",
            "expires_at < now() - (%s * INTERVAL '1 day')",
            otp_days,
        ),
        (
            "operational_outbox_delivered",
            "operational_outbox",
            "id",
            """
            status = 'delivered'
            AND processed_at IS NOT NULL
            AND processed_at < now() - (%s * INTERVAL '1 day')
            """,
            outbox_delivered_days,
        ),
        (
            "webhook_ingress_receipts_delivered",
            "webhook_ingress_receipts",
            "idempotency_key_hash",
            """
            status = 'delivered'
            AND delivered_at IS NOT NULL
            AND delivered_at < now() - (%s * INTERVAL '1 day')
            """,
            receipt_days,
        ),
    ]
    counts: dict[str, int] = {}
    for result_name, table, key_column, predicate, days in targets:
        if dry_run:
            cursor.execute(
                f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE {predicate} LIMIT %s) candidates",
                (days, batch_size),
            )
            counts[result_name] = int(cursor.fetchone()[0])
            continue
        cursor.execute(
            f"""
            WITH candidates AS (
              SELECT {key_column} FROM {table}
              WHERE {predicate}
              ORDER BY {key_column}
              LIMIT %s
              FOR UPDATE SKIP LOCKED
            )
            DELETE FROM {table}
            WHERE {key_column} IN (SELECT {key_column} FROM candidates)
            """,
            (days, batch_size),
        )
        counts[result_name] = cursor.rowcount
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
