from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 734_291_005
BASELINE_NAMES = {"001_initial_schema.sql", "002_web_auth.sql"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward-only SQL migration runner.")
    parser.add_argument("command", choices=("status", "apply", "verify", "baseline"))
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
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
        print("database connection failed; no migration was applied", file=sys.stderr)
        return 1

    try:
        with connection:
            if args.command in {"status", "verify"} and not ledger_exists(connection):
                for path in migration_files():
                    print(f"pending: {path.name}")
                return 0 if args.command == "status" else 1
            ensure_ledger(connection)
            with advisory_lock(connection):
                return run_command(connection, args.command)
    except psycopg.Error:
        print("migration command failed; no partial migration was recorded", file=sys.stderr)
        return 1


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_ledger(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              name TEXT PRIMARY KEY,
              checksum TEXT NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    connection.commit()


def ledger_exists(connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('schema_migrations')")
        return cursor.fetchone()[0] is not None


class advisory_lock:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        return self

    def __exit__(self, *_):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        self.connection.commit()


def applied_migrations(connection) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT name, checksum FROM schema_migrations ORDER BY name")
        return dict(cursor.fetchall())


def verify_applied(files: list[Path], applied: dict[str, str]) -> list[str]:
    errors: list[str] = []
    local = {path.name: checksum(path) for path in files}
    for name, stored_checksum in applied.items():
        if name not in local:
            errors.append(f"missing migration file: {name}")
        elif local[name] != stored_checksum:
            errors.append(f"checksum mismatch: {name}")
    return errors


def run_command(connection, command: str) -> int:
    files = migration_files()
    applied = applied_migrations(connection)
    errors = verify_applied(files, applied)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    if command == "status":
        for path in files:
            state = "applied" if path.name in applied else "pending"
            print(f"{state}: {path.name}")
        return 0
    if command == "verify":
        print(f"verified: {len(applied)} applied migration(s)")
        return 0
    if command == "baseline":
        validate_baseline(connection)
        for path in files:
            if path.name in BASELINE_NAMES and path.name not in applied:
                record_migration(connection, path)
                print(f"baselined: {path.name}")
        return 0

    for path in files:
        if path.name in applied:
            continue
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(path.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
                    (path.name, checksum(path)),
                )
        print(f"applied: {path.name}")
    return 0


def validate_baseline(connection) -> None:
    required = {
        "domains",
        "articles",
        "article_chunks",
        "conversations",
        "messages",
        "verified_identities",
        "web_sessions",
        "otp_challenges",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        )
        existing = {row[0] for row in cursor.fetchall()}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"baseline validation failed; missing tables: {', '.join(missing)}")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'otp_challenges'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%status%'
            LIMIT 1
            """
        )
        if cursor.fetchone() is None:
            raise RuntimeError("baseline validation failed; OTP status constraint is missing")


def record_migration(connection, path: Path) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
            (path.name, checksum(path)),
        )
    connection.commit()


if __name__ == "__main__":
    raise SystemExit(main())
