from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import os
import sys
import time
from typing import Any

from app.core.persistence_sanitize import REDACTION_VERSION, sanitize_for_persistence
from scripts.migrate import MigrationError, advisory_lock


DEFAULT_HASH_VERSION = "hmac-sha256-v1"
DEFAULT_BATCH_SIZE = 250
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
DEFAULT_QUIET_PERIOD_SECONDS = 300
BACKFILL_LOCK_KEY = 734_291_006
FINGERPRINT_CONTEXT = b"conversation-privacy-backfill-fingerprint-v1"
MAX_BATCH_RETRIES = 5
MAX_BATCH_SIZE = 5_000
ROW_LOCK_TIMEOUT_MS = 2_000
STATEMENT_TIMEOUT_MS = 30_000


class BackfillError(MigrationError):
    pass


@dataclass
class BackfillStats:
    batches: int = 0
    conversations: int = 0
    duplicates_merged: int = 0
    messages: int = 0


def main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL")
    secret = os.getenv("PERSISTENCE_HASH_SECRET")
    hash_version = os.getenv("PERSISTENCE_HASH_VERSION", DEFAULT_HASH_VERSION).strip()
    if not database_url or not secret:
        print(
            "DATABASE_URL and PERSISTENCE_HASH_SECRET are required",
            file=sys.stderr,
        )
        return 2

    import psycopg

    connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5"))
    try:
        connection = psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=connect_timeout,
        )
    except psycopg.Error:
        print("database connection failed; backfill did not start", file=sys.stderr)
        return 1

    try:
        with connection:
            with advisory_lock(
                connection,
                key=BACKFILL_LOCK_KEY,
                timeout_seconds=args.lock_timeout_seconds,
            ):
                fingerprint = secret_fingerprint(secret)
                pin_rollout_identity(
                    connection,
                    fingerprint=fingerprint,
                    hash_version=hash_version or DEFAULT_HASH_VERSION,
                )
                stats = run_backfill(
                    connection,
                    secret=secret,
                    hash_version=hash_version or DEFAULT_HASH_VERSION,
                    batch_size=args.batch_size,
                    max_batches=args.max_batches,
                )
                remaining_conversations, remaining_messages = remaining_counts(connection)
                completed = remaining_conversations == 0 and remaining_messages == 0
                if completed:
                    mark_backfill_complete(connection, had_changes=bool(
                        stats.conversations or stats.messages
                    ))
                contract_ready = False
                if args.verify_contract_ready:
                    mark_contract_ready(
                        connection,
                        fingerprint=fingerprint,
                        hash_version=hash_version or DEFAULT_HASH_VERSION,
                        quiet_period_seconds=args.quiet_period_seconds,
                    )
                    contract_ready = True
    except BackfillError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error:
        print("backfill failed; the current batch was rolled back", file=sys.stderr)
        return 1

    print(
        "conversation privacy backfill "
        f"batches={stats.batches} conversations={stats.conversations} "
        f"duplicates_merged={stats.duplicates_merged} messages={stats.messages} "
        f"remaining_conversations={remaining_conversations} "
        f"remaining_messages={remaining_messages} "
        f"contract_ready={str(contract_ready).lower()}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resumable privacy backfill for the conversation contract migration."
    )
    parser.add_argument(
        "--batch-size",
        type=_bounded_batch_size,
        default=_bounded_batch_size(
            os.getenv("CONVERSATION_BACKFILL_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
        ),
    )
    parser.add_argument("--max-batches", type=_positive_int)
    parser.add_argument(
        "--lock-timeout-seconds",
        type=_positive_float,
        default=_positive_float(
            os.getenv(
                "CONVERSATION_BACKFILL_LOCK_TIMEOUT_SECONDS",
                str(DEFAULT_LOCK_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--verify-contract-ready",
        action="store_true",
        help="mark the contract migration ready after an exclusive consistency check",
    )
    parser.add_argument(
        "--quiet-period-seconds",
        type=_nonnegative_int,
        default=_nonnegative_int(
            os.getenv(
                "CONVERSATION_BACKFILL_QUIET_PERIOD_SECONDS",
                str(DEFAULT_QUIET_PERIOD_SECONDS),
            )
        ),
    )
    return parser.parse_args(argv)


def run_backfill(
    connection: Any,
    *,
    secret: str,
    hash_version: str,
    batch_size: int,
    max_batches: int | None,
) -> BackfillStats:
    stats = BackfillStats()
    while max_batches is None or stats.batches < max_batches:
        conversations, duplicates, messages = _run_batch_with_retry(
            connection,
            secret=secret,
            hash_version=hash_version,
            batch_size=batch_size,
        )
        if not conversations and not messages:
            break
        stats.batches += 1
        stats.conversations += conversations
        stats.duplicates_merged += duplicates
        stats.messages += messages
    return stats


def pin_rollout_identity(
    connection: Any,
    *,
    fingerprint: str,
    hash_version: str,
) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            set_local_timeouts(cursor)
            cursor.execute(
                """
                SELECT phase, hash_secret_fingerprint, hash_version
                FROM conversation_privacy_rollout
                WHERE singleton = true
                FOR UPDATE
                """
            )
            row = cursor.fetchone()
            if row is None:
                raise BackfillError(
                    "conversation privacy rollout is missing; apply migration 006 first"
                )
            phase, stored_fingerprint, stored_version = row
            if phase == "contracted":
                raise BackfillError("conversation privacy rollout is already contracted")
            if (stored_fingerprint is None) != (stored_version is None):
                raise BackfillError(
                    "conversation privacy rollout identity is partially configured"
                )
            if stored_fingerprint is None:
                cursor.execute(
                    """
                    UPDATE conversation_privacy_rollout
                    SET hash_secret_fingerprint = %s,
                        hash_version = %s,
                        updated_at = clock_timestamp()
                    WHERE singleton = true
                    """,
                    (fingerprint, hash_version),
                )
                return
            if stored_fingerprint != fingerprint or stored_version != hash_version:
                raise BackfillError(
                    "backfill hash secret fingerprint or version differs from "
                    "the identity pinned on the first run"
                )


def _run_batch_with_retry(
    connection: Any,
    *,
    secret: str,
    hash_version: str,
    batch_size: int,
) -> tuple[int, int, int]:
    import psycopg

    retryable = (
        psycopg.errors.DeadlockDetected,
        psycopg.errors.LockNotAvailable,
        psycopg.errors.QueryCanceled,
        psycopg.errors.SerializationFailure,
        psycopg.errors.UniqueViolation,
    )
    for attempt in range(MAX_BATCH_RETRIES):
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    set_local_timeouts(cursor)
                    conversations, duplicates = backfill_conversation_batch(
                        cursor,
                        secret=secret,
                        hash_version=hash_version,
                        batch_size=batch_size,
                    )
                    messages = backfill_message_batch(cursor, batch_size=batch_size)
                    if conversations or messages:
                        cursor.execute(
                            """
                            UPDATE conversation_privacy_rollout
                            SET phase = 'expanded',
                                backfill_completed_at = NULL,
                                contract_ready_at = NULL,
                                updated_at = now()
                            WHERE singleton = true
                            """
                        )
                    return conversations, duplicates, messages
        except retryable:
            if attempt + 1 == MAX_BATCH_RETRIES:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError("unreachable")


def backfill_conversation_batch(
    cursor: Any,
    *,
    secret: str,
    hash_version: str,
    batch_size: int,
) -> tuple[int, int]:
    cursor.execute(
        """
        SELECT id, domain_id, channel, status, session_id
        FROM conversations
        WHERE session_id IS NOT NULL
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
        """,
        (batch_size,),
    )
    rows = cursor.fetchall()
    updated = 0
    duplicates_merged = 0
    active_statuses = ("bot", "handoff_pending", "human_active")

    for conversation_id, domain_id, channel, status, raw_session_id in rows:
        session_hash = hash_session(raw_session_id, secret)
        survivor_id = None
        if status in active_statuses:
            cursor.execute(
                """
                SELECT id
                FROM conversations
                WHERE domain_id = %s
                  AND channel = %s
                  AND session_hash = %s
                  AND status IN ('bot', 'handoff_pending', 'human_active')
                  AND id <> %s
                ORDER BY updated_at DESC, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (domain_id, channel, session_hash, conversation_id),
            )
            survivor = cursor.fetchone()
            survivor_id = survivor[0] if survivor else None

        if survivor_id is not None:
            merge_conversation(
                cursor,
                survivor_id=survivor_id,
                duplicate_id=conversation_id,
                session_hash=session_hash,
                hash_version=hash_version,
            )
            cursor.execute(
                """
                UPDATE conversations
                SET session_hash = %s,
                    session_hash_version = %s,
                    last_message_at = COALESCE(last_message_at, updated_at, created_at),
                    updated_at = now()
                WHERE id = %s
                """,
                (session_hash, hash_version, survivor_id),
            )
            duplicates_merged += 1
        else:
            cursor.execute(
                """
                UPDATE conversations
                SET session_hash = %s,
                    session_hash_version = %s,
                    session_id = NULL,
                    last_message_at = COALESCE(last_message_at, updated_at, created_at),
                    updated_at = now()
                WHERE id = %s
                """,
                (session_hash, hash_version, conversation_id),
            )
        updated += 1
    return updated, duplicates_merged


def merge_conversation(
    cursor: Any,
    *,
    survivor_id: Any,
    duplicate_id: Any,
    session_hash: str,
    hash_version: str,
) -> None:
    cursor.execute(
        """
        UPDATE messages AS source
        SET conversation_id = %s
        WHERE source.conversation_id = %s
          AND (
            source.turn_id IS NULL
            OR NOT EXISTS (
              SELECT 1
              FROM messages AS existing
              WHERE existing.conversation_id = %s
                AND existing.turn_id = source.turn_id
                AND existing.role = source.role
            )
          )
        """,
        (survivor_id, duplicate_id, survivor_id),
    )
    cursor.execute(
        """
        UPDATE conversations
        SET status = 'merged',
            session_hash = %s,
            session_hash_version = %s,
            session_id = NULL,
            last_message_at = COALESCE(last_message_at, updated_at, created_at),
            updated_at = now()
        WHERE id = %s
        """,
        (session_hash, hash_version, duplicate_id),
    )


def backfill_message_batch(cursor: Any, *, batch_size: int) -> int:
    cursor.execute(
        """
        SELECT id, content
        FROM messages
        WHERE redaction_version = 'legacy-unverified'
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
        """,
        (batch_size,),
    )
    rows = cursor.fetchall()
    for message_id, raw_content in rows:
        sanitized = sanitize_for_persistence(raw_content)
        if sanitized is None:
            raise BackfillError("message sanitization returned empty content")
        cursor.execute(
            """
            UPDATE messages
            SET content = %s, redaction_version = %s
            WHERE id = %s
            """,
            (sanitized, REDACTION_VERSION, message_id),
        )
    return len(rows)


def remaining_counts(connection: Any) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT count(*) FROM conversations WHERE session_id IS NOT NULL),
              (SELECT count(*) FROM messages WHERE redaction_version = 'legacy-unverified')
            """
        )
        conversations, messages = cursor.fetchone()
    return int(conversations), int(messages)


def mark_backfill_complete(connection: Any, *, had_changes: bool) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            set_local_timeouts(cursor)
            cursor.execute("LOCK TABLE conversations IN SHARE MODE")
            cursor.execute("LOCK TABLE messages IN SHARE MODE")
            conversations, messages = _remaining_counts_with_cursor(cursor)
            if conversations or messages:
                return
            cursor.execute(
                """
                UPDATE conversation_privacy_rollout
                SET phase = CASE
                      WHEN phase = 'contract_ready' AND NOT %s
                        THEN 'contract_ready'
                      ELSE 'backfilled'
                    END,
                    backfill_completed_at = CASE
                      WHEN %s OR backfill_completed_at IS NULL THEN now()
                      ELSE backfill_completed_at
                    END,
                    contract_ready_at = CASE
                      WHEN %s THEN NULL
                      ELSE contract_ready_at
                    END,
                    updated_at = now()
                WHERE singleton = true
                """,
                (had_changes, had_changes, had_changes),
            )


def mark_contract_ready(
    connection: Any,
    *,
    fingerprint: str,
    hash_version: str,
    quiet_period_seconds: int,
) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            set_local_timeouts(cursor)
            cursor.execute("LOCK TABLE conversations IN SHARE MODE")
            cursor.execute("LOCK TABLE messages IN SHARE MODE")
            conversations, messages = _remaining_counts_with_cursor(cursor)
            if conversations or messages:
                raise BackfillError(
                    "contract readiness failed; privacy backfill still has pending rows"
                )
            cursor.execute(
                """
                SELECT
                  backfill_completed_at,
                  hash_secret_fingerprint = %s
                    AND hash_version = %s,
                  last_legacy_write_at IS NULL
                    OR last_legacy_write_at <=
                      clock_timestamp() - (%s * interval '1 second')
                FROM conversation_privacy_rollout
                WHERE singleton = true
                """,
                (fingerprint, hash_version, quiet_period_seconds),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None:
                raise BackfillError(
                    "contract readiness failed; backfill completion is not recorded"
                )
            if not row[1]:
                raise BackfillError(
                    "contract readiness failed; pinned hash identity changed"
                )
            if not row[2]:
                raise BackfillError(
                    "contract readiness failed; legacy writer quiet period has not elapsed"
                )
            cursor.execute(
                """
                UPDATE conversation_privacy_rollout
                SET phase = 'contract_ready',
                    contract_ready_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                WHERE singleton = true
                """
            )


def _remaining_counts_with_cursor(cursor: Any) -> tuple[int, int]:
    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM conversations WHERE session_id IS NOT NULL),
          (SELECT count(*) FROM messages WHERE redaction_version = 'legacy-unverified')
        """
    )
    conversations, messages = cursor.fetchone()
    return int(conversations), int(messages)


def set_local_timeouts(cursor: Any) -> None:
    cursor.execute(
        "SELECT set_config('lock_timeout', %s, true)",
        (f"{ROW_LOCK_TIMEOUT_MS}ms",),
    )
    cursor.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (f"{STATEMENT_TIMEOUT_MS}ms",),
    )


def hash_session(value: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        value.strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def secret_fingerprint(secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        FINGERPRINT_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _bounded_batch_size(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError(
            f"must be less than or equal to {MAX_BATCH_SIZE}"
        )
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
