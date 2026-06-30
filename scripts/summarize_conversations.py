"""Nightly conversation summarization batch (layered-persistence plan, Fase 3).

Reads closed/inactive conversations, sanitizes every turn before the model, asks
gpt-4o-mini for a structured record and upserts it idempotently into
``conversation_summaries``. Dark by default: refuses to write unless
``ENABLE_CONVERSATION_SUMMARY=true`` (``--dry-run`` only counts eligible
conversations and never calls the model).

Run via a systemd timer (~3h), never a cron inside the app. Logs sanitized
metrics only; no PII, no raw session_id (see docs/architecture/observability.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _eligible_count(connection, *, inactivity_hours: int, min_turns: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM conversations c
            WHERE c.last_message_at IS NOT NULL
              AND c.last_message_at < now() - make_interval(hours => %s)
              AND (
                SELECT count(*) FROM messages m WHERE m.conversation_id = c.id
              ) >= %s
              AND NOT EXISTS (
                SELECT 1 FROM conversation_summaries s
                JOIN domains d ON d.name = s.domain
                WHERE d.id = c.domain_id AND s.conversation_key = c.id::text
              )
            """,
            (inactivity_hours, min_turns),
        )
        return int(cursor.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize closed conversations into the warehouse.")
    parser.add_argument("--inactivity-hours", type=int, default=24)
    parser.add_argument("--min-turns", type=int, default=2)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-summarize already-summarized conversations")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")

    enabled = os.getenv("ENABLE_CONVERSATION_SUMMARY", "").strip().lower() == "true"
    if not enabled and not args.dry_run:
        print(
            json.dumps({"event": "conversation_summary_disabled",
                        "hint": "set ENABLE_CONVERSATION_SUMMARY=true or use --dry-run"}),
            file=sys.stderr,
        )
        return 0

    import psycopg

    connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5") or "5")
    with psycopg.connect(database_url, connect_timeout=connect_timeout) as connection:
        if args.dry_run:
            count = _eligible_count(
                connection,
                inactivity_hours=args.inactivity_hours,
                min_turns=args.min_turns,
            )
            print(json.dumps({"event": "conversation_summary_dry_run", "eligible": count}))
            return 0

        from app.conversations.summary import run_summary_batch
        from app.llm.wrapper import LLMWrapper

        provider = LLMWrapper(model=args.model)
        stats = run_summary_batch(
            connection,
            provider,
            model=args.model,
            inactivity_hours=args.inactivity_hours,
            min_turns=args.min_turns,
            limit=args.limit,
            force=args.force,
        )
    print(json.dumps({"event": "conversation_summary_completed", **stats}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
