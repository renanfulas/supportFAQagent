from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from app.core.migration_checksum import (
    canonical_migration_bytes,
    migration_checksum,
    migration_checksum_variants,
)
from app.db.schema_contract import CONTRACT_MIGRATION, structural_drift

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 734_291_005
BASELINE_NAMES = {"001_initial_schema.sql", "002_web_auth.sql"}
BASELINE_OTP_STATES = frozenset(
    {"pending", "consumed", "expired", "delivery_failed"}
)
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 120.0
LOCK_RETRY_SECONDS = 0.1
BASELINE_REQUIRED_COLUMNS = {
    "domains": {"id", "name", "display_name", "status"},
    "articles": {"id", "domain_id", "source", "content_hash", "status"},
    "article_chunks": {
        "id",
        "article_id",
        "domain_id",
        "chunk_index",
        "chunk_text",
        "content_hash",
        "embedding",
    },
    "conversations": {"id", "domain_id", "channel", "session_id", "status"},
    "messages": {"id", "conversation_id", "role", "content"},
    "verified_identities": {"id", "channel", "phone_hash", "status"},
    "web_sessions": {"id", "anonymous_session_hash", "verified_identity_id"},
    "otp_challenges": {"id", "code_digest", "attempts_remaining", "status"},
}
BASELINE_REQUIRED_NOT_NULL_COLUMNS = {
    "domains": {"id", "name", "display_name", "status"},
    "articles": {"id", "domain_id", "source", "content_hash", "status"},
    "article_chunks": {
        "id",
        "article_id",
        "domain_id",
        "chunk_index",
        "chunk_text",
        "content_hash",
    },
    "conversations": {"id", "domain_id", "channel", "session_id", "status"},
    "messages": {"id", "conversation_id", "role", "content"},
    "verified_identities": {"id", "channel", "phone_hash", "status"},
    "web_sessions": {"id", "anonymous_session_hash"},
    "otp_challenges": {"id", "code_digest", "attempts_remaining", "status"},
}
BASELINE_REQUIRED_EXTENSIONS = {"pgcrypto", "vector"}
BASELINE_REQUIRED_INDEXES = {
    "idx_articles_domain_status",
    "idx_articles_domain_source_type_external",
    "idx_chunks_domain_article",
    "idx_chunks_metadata_gin",
    "idx_conversations_session_domain",
    "idx_conversations_domain_channel_external",
    "idx_messages_conversation_created",
    "idx_verified_identities_channel_status",
    "idx_web_sessions_identity",
    "idx_web_sessions_last_seen",
    "idx_otp_challenges_candidate_created",
    "idx_otp_challenges_status_expires",
    "idx_otp_challenges_expires_at",
}
BASELINE_REQUIRED_CONSTRAINTS = {
    "domains": ("PRIMARY KEY (id)", "UNIQUE (name)"),
    "articles": (
        "PRIMARY KEY (id)",
        "UNIQUE (domain_id, source)",
        "FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE",
    ),
    "article_chunks": (
        "PRIMARY KEY (id)",
        "UNIQUE (article_id, chunk_index)",
        "FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE",
        "FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE",
    ),
    "conversations": (
        "PRIMARY KEY (id)",
        "FOREIGN KEY (domain_id) REFERENCES domains(id)",
    ),
    "messages": (
        "PRIMARY KEY (id)",
        "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE",
    ),
    "verified_identities": (
        "PRIMARY KEY (id)",
        "UNIQUE (channel, phone_hash)",
    ),
    "web_sessions": (
        "PRIMARY KEY (id)",
        "UNIQUE (anonymous_session_hash)",
        "FOREIGN KEY (verified_identity_id) REFERENCES verified_identities(id) ON DELETE SET NULL",
    ),
    "otp_challenges": (
        "PRIMARY KEY (id)",
        "CHECK ((attempts_remaining >= 0))",
    ),
}


class MigrationError(RuntimeError):
    """Expected operational failure that is safe to show to an operator."""


class MigrationLockTimeout(MigrationError):
    pass


class MigrationValidationError(MigrationError):
    pass


def main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 2

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5"))
    try:
        lock_timeout = _positive_float_env(
            "DATABASE_MIGRATION_LOCK_TIMEOUT_SECONDS",
            DEFAULT_LOCK_TIMEOUT_SECONDS,
        )
        statement_timeout = _positive_float_env(
            "DATABASE_MIGRATION_STATEMENT_TIMEOUT_SECONDS",
            DEFAULT_STATEMENT_TIMEOUT_SECONDS,
        )
    except MigrationValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        existing_options = conninfo_to_dict(database_url).get("options", "").strip()
        timeout_options = (
            f"-c lock_timeout={int(lock_timeout * 1000)} "
            f"-c statement_timeout={int(statement_timeout * 1000)}"
        )
        connection = psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=connect_timeout,
            options=" ".join(part for part in (existing_options, timeout_options) if part),
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
            with advisory_lock(connection, timeout_seconds=lock_timeout):
                return run_command(connection, args.command, target=args.target)
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error:
        print(
            "migration command failed; the failing migration was rolled back "
            "and earlier applied migrations remain recorded",
            file=sys.stderr,
        )
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forward-only SQL migration runner.")
    parser.add_argument("command", choices=("status", "apply", "verify", "baseline"))
    parser.add_argument(
        "--target",
        metavar="VERSION_OR_FILE",
        help="apply through this migration, for example --target 006",
    )
    args = parser.parse_args(argv)
    if args.target and args.command != "apply":
        parser.error("--target is supported only with the apply command")
    return args


def migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise MigrationValidationError("no migration files were found")
    return files


def checksum(path: Path) -> str:
    return migration_checksum(path)


def checksum_variants(path: Path) -> set[str]:
    return migration_checksum_variants(path)


def current_schema_name(connection: Any) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    if row is None or not row[0]:
        raise MigrationValidationError("current_schema() did not resolve a schema")
    return str(row[0])


def ledger_identifier(connection: Any):
    from psycopg import sql

    return sql.Identifier(current_schema_name(connection), "schema_migrations")


def ensure_ledger(connection: Any) -> None:
    from psycopg import sql

    ledger = ledger_identifier(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                  name TEXT PRIMARY KEY,
                  checksum TEXT NOT NULL,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
                """
            ).format(ledger)
        )
    connection.commit()


def ledger_exists(connection: Any) -> bool:
    schema = current_schema_name(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_tables
              WHERE schemaname = %s
                AND tablename = 'schema_migrations'
            )
            """,
            (schema,),
        )
        return bool(cursor.fetchone()[0])


class advisory_lock:
    def __init__(
        self,
        connection: Any,
        *,
        key: int = LOCK_KEY,
        timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        retry_seconds: float = LOCK_RETRY_SECONDS,
    ) -> None:
        self.connection = connection
        self.key = key
        self.timeout_seconds = timeout_seconds
        self.retry_seconds = retry_seconds
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
                self.acquired = bool(cursor.fetchone()[0])
            if self.acquired:
                return self
            if time.monotonic() >= deadline:
                raise MigrationLockTimeout(
                    f"migration advisory lock timed out after {self.timeout_seconds:g}s"
                )
            time.sleep(self.retry_seconds)

    def __exit__(self, *_):
        if not self.acquired:
            return False
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        self.connection.commit()
        self.acquired = False
        return False


def applied_migrations(connection: Any) -> dict[str, str]:
    from psycopg import sql

    ledger = ledger_identifier(connection)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT name, checksum FROM {} ORDER BY name").format(ledger))
        return dict(cursor.fetchall())


def verify_applied(files: list[Path], applied: dict[str, str]) -> list[str]:
    errors: list[str] = []
    local = {path.name: path for path in files}
    for name, stored_checksum in applied.items():
        if name not in local:
            errors.append(f"missing migration file: {name}")
        elif stored_checksum not in checksum_variants(local[name]):
            errors.append(f"checksum mismatch: {name}")
    return errors


def pending_migrations(files: list[Path], applied: dict[str, str]) -> list[Path]:
    return [path for path in files if path.name not in applied]


def resolve_target(files: list[Path], target: str | None) -> int:
    if target is None:
        return len(files) - 1
    matches = [
        index
        for index, path in enumerate(files)
        if path.name == target or path.name.startswith(f"{target}_")
    ]
    if len(matches) != 1:
        raise MigrationValidationError(
            f"migration target must identify exactly one file: {target}"
        )
    return matches[0]


def run_command(connection: Any, command: str, *, target: str | None = None) -> int:
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
        pending = pending_migrations(files, applied)
        if pending:
            for path in pending:
                print(f"pending: {path.name}", file=sys.stderr)
            return 1
        if CONTRACT_MIGRATION in applied:
            with connection.cursor() as cursor:
                drift = structural_drift(cursor, current_schema_name(connection))
            if drift:
                print("\n".join(drift), file=sys.stderr)
                return 1
        print(f"verified: {len(applied)} applied migration(s)")
        return 0
    if command == "baseline":
        validate_baseline(connection)
        paths = [
            path
            for path in files
            if path.name in BASELINE_NAMES and path.name not in applied
        ]
        with connection.transaction():
            for path in paths:
                record_migration(connection, path)
        for path in paths:
            print(f"baselined: {path.name}")
        return 0

    target_index = resolve_target(files, target)
    files_after_target = {path.name for path in files[target_index + 1 :]}
    applied_after_target = sorted(files_after_target.intersection(applied))
    if applied_after_target:
        raise MigrationValidationError(
            "target is behind already applied migrations: "
            + ", ".join(applied_after_target)
        )

    for path in files[: target_index + 1]:
        if path.name in applied:
            continue
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(path.read_text(encoding="utf-8"))
                    record_migration(connection, path, cursor=cursor)
        except Exception as exc:
            raise MigrationError(f"migration failed: {path.name}") from exc
        print(f"applied: {path.name}")
    return 0


def validate_baseline(connection: Any) -> None:
    schema = current_schema_name(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = %s",
            (schema,),
        )
        existing = {str(row[0]) for row in cursor.fetchall()}
    missing = sorted(set(BASELINE_REQUIRED_COLUMNS) - existing)
    if missing:
        raise MigrationValidationError(
            f"baseline validation failed; missing tables: {', '.join(missing)}"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = ANY(%s)
            """,
            (schema, list(BASELINE_REQUIRED_COLUMNS)),
        )
        columns_by_table: dict[str, set[str]] = {
            table: set() for table in BASELINE_REQUIRED_COLUMNS
        }
        not_null_by_table: dict[str, set[str]] = {
            table: set() for table in BASELINE_REQUIRED_COLUMNS
        }
        for table, column, is_nullable in cursor.fetchall():
            columns_by_table[str(table)].add(str(column))
            if is_nullable == "NO":
                not_null_by_table[str(table)].add(str(column))
    missing_columns = [
        f"{table}.{column}"
        for table, required_columns in BASELINE_REQUIRED_COLUMNS.items()
        for column in sorted(required_columns - columns_by_table[table])
    ]
    if missing_columns:
        raise MigrationValidationError(
            "baseline validation failed; missing columns: " + ", ".join(missing_columns)
        )
    nullable_columns = [
        f"{table}.{column}"
        for table, required_columns in BASELINE_REQUIRED_NOT_NULL_COLUMNS.items()
        for column in sorted(required_columns - not_null_by_table[table])
    ]
    if nullable_columns:
        raise MigrationValidationError(
            "baseline validation failed; required NOT NULL columns are nullable: "
            + ", ".join(nullable_columns)
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extname FROM pg_extension WHERE extname = ANY(%s)",
            (list(BASELINE_REQUIRED_EXTENSIONS),),
        )
        extensions = {str(row[0]) for row in cursor.fetchall()}
    missing_extensions = sorted(BASELINE_REQUIRED_EXTENSIONS - extensions)
    if missing_extensions:
        raise MigrationValidationError(
            "baseline validation failed; missing extensions: "
            + ", ".join(missing_extensions)
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_catalog.pg_attribute AS attribute
            JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = %s
              AND relation.relname = 'article_chunks'
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """,
            (schema,),
        )
        vector_type = cursor.fetchone()
    if vector_type is None or vector_type[0] != "vector(1536)":
        actual = vector_type[0] if vector_type else "missing"
        raise MigrationValidationError(
            "baseline validation failed; article_chunks.embedding must be "
            f"vector(1536), got {actual}"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation.relname, pg_catalog.pg_get_constraintdef(constraint_row.oid)
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = %s
              AND relation.relname = ANY(%s)
              AND constraint_row.contype IN ('p', 'u', 'f', 'c')
            """,
            (schema, list(BASELINE_REQUIRED_CONSTRAINTS)),
        )
        definitions_by_table: dict[str, list[str]] = {
            table: [] for table in BASELINE_REQUIRED_CONSTRAINTS
        }
        for table, definition in cursor.fetchall():
            definitions_by_table[str(table)].append(_normalize_sql(str(definition)))
    missing_constraints = [
        f"{table}: {required}"
        for table, required_definitions in BASELINE_REQUIRED_CONSTRAINTS.items()
        for required in required_definitions
        if _normalize_sql(required) not in definitions_by_table[table]
    ]
    if missing_constraints:
        raise MigrationValidationError(
            "baseline validation failed; missing critical constraints: "
            + "; ".join(missing_constraints)
        )

    otp_definitions = [
        definition
        for definition in definitions_by_table["otp_challenges"]
        if "status" in definition.lower()
    ]
    states = otp_states_from_constraint_definitions(otp_definitions)
    if states != BASELINE_OTP_STATES:
        expected = ", ".join(sorted(BASELINE_OTP_STATES))
        actual = ", ".join(sorted(states)) if states else "missing"
        raise MigrationValidationError(
            "baseline validation failed; OTP status states must match "
            f"002_web_auth.sql exactly (expected: {expected}; actual: {actual})"
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = %s
            """,
            (schema,),
        )
        indexes = {str(row[0]) for row in cursor.fetchall()}
    missing_indexes = sorted(BASELINE_REQUIRED_INDEXES - indexes)
    if missing_indexes:
        raise MigrationValidationError(
            "baseline validation failed; missing critical indexes: "
            + ", ".join(missing_indexes)
        )


def record_migration(connection: Any, path: Path, *, cursor: Any | None = None) -> None:
    from psycopg import sql

    ledger = ledger_identifier(connection)
    owns_cursor = cursor is None
    active_cursor = cursor or connection.cursor()
    try:
        active_cursor.execute(
            sql.SQL("INSERT INTO {} (name, checksum) VALUES (%s, %s)").format(ledger),
            (path.name, checksum(path)),
        )
    finally:
        if owns_cursor:
            active_cursor.close()


def otp_states_from_constraint_definitions(definitions: list[str]) -> frozenset[str]:
    if len(definitions) != 1:
        return frozenset()
    return frozenset(
        value.replace("''", "'")
        for value in re.findall(r"'((?:''|[^'])*)'", definitions[0])
    )


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise MigrationValidationError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise MigrationValidationError(f"{name} must be a positive number")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
