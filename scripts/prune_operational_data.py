from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune expired operational data.")
    parser.add_argument(
        "--conversation-days",
        type=int,
        default=int(os.getenv("CONVERSATION_RETENTION_DAYS", "60")),
    )
    parser.add_argument("--otp-days", type=int, default=7)
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    if args.conversation_days < 1 or args.otp_days < 1:
        parser.error("retention days must be positive")

    import psycopg

    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM feedback WHERE created_at < now() - (%s * INTERVAL '1 day')",
                    (args.conversation_days,),
                )
                feedback_deleted = cursor.rowcount
                cursor.execute(
                    "DELETE FROM chat_audits WHERE created_at < now() - (%s * INTERVAL '1 day')",
                    (args.conversation_days,),
                )
                audits_deleted = cursor.rowcount
                cursor.execute(
                    "DELETE FROM otp_challenges WHERE expires_at < now() - (%s * INTERVAL '1 day')",
                    (args.otp_days,),
                )
                otp_deleted = cursor.rowcount
    print(
        f"pruned feedback={feedback_deleted} chat_audits={audits_deleted} "
        f"otp_challenges={otp_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
