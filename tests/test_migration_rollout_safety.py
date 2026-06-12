from __future__ import annotations

from pathlib import Path

import pytest

from scripts.backfill_conversation_privacy import (
    backfill_message_batch,
    parse_args,
    secret_fingerprint,
)
from scripts.migrate import (
    MigrationLockTimeout,
    advisory_lock,
    checksum,
    checksum_variants,
    otp_states_from_constraint_definitions,
    parse_args as parse_migrate_args,
    pending_migrations,
    resolve_target,
    run_command,
    verify_applied,
)


ROOT = Path(__file__).resolve().parents[1]


def test_verify_fails_when_any_migration_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    applied_path = tmp_path / "001_applied.sql"
    pending_path = tmp_path / "002_pending.sql"
    applied_path.write_text("SELECT 1;", encoding="utf-8")
    pending_path.write_text("SELECT 2;", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.migrate.migration_files",
        lambda: [applied_path, pending_path],
    )
    monkeypatch.setattr(
        "scripts.migrate.applied_migrations",
        lambda connection: {applied_path.name: checksum(applied_path)},
    )

    assert run_command(object(), "verify") == 1
    assert "pending: 002_pending.sql" in capsys.readouterr().err


def test_pending_migrations_preserves_file_order(tmp_path: Path) -> None:
    first = tmp_path / "001_first.sql"
    second = tmp_path / "002_second.sql"

    assert pending_migrations([first, second], {first.name: "checksum"}) == [second]


def test_checksum_is_portable_between_lf_and_crlf(tmp_path: Path) -> None:
    lf = tmp_path / "001_lf.sql"
    crlf = tmp_path / "001_crlf.sql"
    lf.write_bytes(b"SELECT 1;\nSELECT 2;\n")
    crlf.write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")

    assert checksum(lf) == checksum(crlf)
    assert verify_applied([lf], {lf.name: checksum(lf)}) == []
    assert hashlib_sha256(crlf.read_bytes()) in checksum_variants(lf)


def test_apply_target_resolves_version_or_full_filename(tmp_path: Path) -> None:
    files = [
        tmp_path / "005_before.sql",
        tmp_path / "006_expand.sql",
        tmp_path / "007_contract.sql",
    ]

    assert resolve_target(files, "006") == 1
    assert resolve_target(files, "006_expand.sql") == 1
    assert parse_migrate_args(["apply", "--target", "006"]).target == "006"


def test_runner_preserves_existing_connection_options_for_schema_isolation() -> None:
    source = (ROOT / "scripts" / "migrate.py").read_text(encoding="utf-8")

    assert "conninfo_to_dict(database_url)" in source
    assert "existing_options" in source
    assert "timeout_options" in source


def test_baseline_otp_constraint_requires_exact_002_states() -> None:
    baseline = (
        "CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, "
        "'expired'::text, 'delivery_failed'::text])))"
    )
    extra_state = baseline.replace(
        "'delivery_failed'::text",
        "'delivery_failed'::text, 'exhausted'::text",
    )

    assert otp_states_from_constraint_definitions([baseline]) == frozenset(
        {"pending", "consumed", "expired", "delivery_failed"}
    )
    assert otp_states_from_constraint_definitions([extra_state]) != frozenset(
        {"pending", "consumed", "expired", "delivery_failed"}
    )
    assert otp_states_from_constraint_definitions([baseline, baseline]) == frozenset()


def test_baseline_catalog_query_ignores_postgres_18_not_null_constraints() -> None:
    source = (ROOT / "scripts" / "migrate.py").read_text(encoding="utf-8")

    assert "constraint_row.contype IN ('p', 'u', 'f', 'c')" in source


def test_advisory_lock_times_out_without_using_blocking_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = LockConnection([False, False])
    clock = iter([0.0, 0.02])
    monkeypatch.setattr("scripts.migrate.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("scripts.migrate.time.sleep", lambda _: None)

    with pytest.raises(MigrationLockTimeout, match="timed out"):
        with advisory_lock(
            connection,
            key=42,
            timeout_seconds=0.01,
            retry_seconds=0,
        ):
            pass

    sql = " ".join(call[0] for call in connection.calls)
    assert "pg_try_advisory_lock" in sql
    assert "pg_advisory_lock(" not in sql.replace("pg_try_advisory_lock(", "")


def test_advisory_lock_releases_acquired_lock() -> None:
    connection = LockConnection([True, True])

    with advisory_lock(connection, key=42, timeout_seconds=1):
        pass

    assert any("pg_advisory_unlock" in sql for sql, _ in connection.calls)
    assert connection.commits == 1


def test_backfill_cli_exposes_resumable_and_contract_ready_controls() -> None:
    args = parse_args(
        [
            "--batch-size",
            "25",
            "--max-batches",
            "3",
            "--verify-contract-ready",
            "--quiet-period-seconds",
            "0",
        ]
    )

    assert args.batch_size == 25
    assert args.max_batches == 3
    assert args.verify_contract_ready is True
    assert args.quiet_period_seconds == 0


def test_message_backfill_is_bounded_and_sanitizes_before_update() -> None:
    cursor = BatchCursor(rows=[("message-id", "email=user@example.com")])

    assert backfill_message_batch(cursor, batch_size=10) == 1

    select_sql, select_params = cursor.calls[0]
    update_sql, update_params = cursor.calls[1]
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert "LIMIT %s" in select_sql
    assert select_params == (10,)
    assert "UPDATE messages" in update_sql
    assert update_params is not None
    assert "user@example.com" not in str(update_params)


def test_expand_and_contract_migrations_encode_safe_rollout_guards() -> None:
    expand = (ROOT / "migrations" / "006_conversations_messages.sql").read_text(
        encoding="utf-8"
    )
    contract = (
        ROOT / "migrations" / "007_remove_raw_conversation_sessions.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER COLUMN session_id DROP NOT NULL" in expand
    assert "conversations_legacy_writer_guard" in expand
    assert "contract_ready_at = NULL" in expand
    assert "hash_secret_fingerprint TEXT" in expand
    assert "'contract_ready'" not in expand.split(
        "INSERT INTO conversation_privacy_rollout", maxsplit=1
    )[1].split("CREATE FUNCTION", maxsplit=1)[0]
    assert "clock_timestamp()" in expand
    assert "CREATE UNIQUE INDEX idx_conversations_active_session" in expand
    assert "LOCK TABLE conversations IN ACCESS EXCLUSIVE MODE" in contract
    assert "LOCK TABLE messages IN ACCESS EXCLUSIVE MODE" in contract
    assert "SET LOCAL lock_timeout = '10s'" in contract
    assert "phase = 'contract_ready'" in contract
    assert "hash_secret_fingerprint IS NOT NULL" in contract
    assert "conversation.session_hash_version <> rollout.hash_version" in contract
    assert "DROP COLUMN session_id" in contract


def test_backfill_retires_duplicates_without_deleting_legacy_writer_target() -> None:
    source = (
        ROOT / "scripts" / "backfill_conversation_privacy.py"
    ).read_text(encoding="utf-8")

    assert "SET status = 'merged'" in source
    assert "DELETE FROM conversations" not in source


def test_backfill_secret_fingerprint_is_stable_and_secret_specific() -> None:
    assert secret_fingerprint("secret-a") == secret_fingerprint("secret-a")
    assert secret_fingerprint("secret-a") != secret_fingerprint("secret-b")
    assert "secret-a" not in secret_fingerprint("secret-a")


def hashlib_sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


class LockCursor:
    def __init__(self, connection: "LockConnection") -> None:
        self.connection = connection
        self.row: tuple[bool] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.connection.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            self.row = (self.connection.results.pop(0),)
        elif "pg_advisory_unlock" in sql:
            self.row = (self.connection.results.pop(0),)

    def fetchone(self) -> tuple[bool]:
        assert self.row is not None
        return self.row


class LockConnection:
    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.calls: list[tuple[str, tuple | None]] = []
        self.commits = 0

    def cursor(self) -> LockCursor:
        return LockCursor(self)

    def commit(self) -> None:
        self.commits += 1


class BatchCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list[tuple[str, str]]:
        return self.rows
