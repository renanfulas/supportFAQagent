from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
ROOT = Path(__file__).resolve().parents[2]


def test_legacy_conversations_require_private_backfill_before_enforcement() -> None:
    assert DATABASE_URL
    import psycopg
    from psycopg.conninfo import make_conninfo

    schema = f"conversation_upgrade_{uuid4().hex[:12]}"
    schema_url = make_conninfo(
        DATABASE_URL,
        options=f"-c search_path={schema},public",
    )
    env = {
        **os.environ,
        "DATABASE_URL": schema_url,
        "PERSISTENCE_HASH_SECRET": "upgrade-test-secret",
        "PERSISTENCE_HASH_VERSION": "hmac-sha256-v1",
    }

    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with psycopg.connect(schema_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    for name in ("001_initial_schema.sql", "002_web_auth.sql"):
                        cursor.execute((ROOT / "migrations" / name).read_text(encoding="utf-8"))
                    cursor.execute(
                        """
                        INSERT INTO domains (name, display_name)
                        VALUES ('suporte-vps-whatsapp', 'Suporte VPS e WhatsApp')
                        RETURNING id
                        """
                    )
                    domain_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO conversations (domain_id, channel, session_id)
                        VALUES (%s, 'whatsapp', 'raw-session'),
                               (%s, 'whatsapp', 'raw-session')
                        RETURNING id
                        """,
                        (domain_id, domain_id),
                    )
                    conversations = [row[0] for row in cursor.fetchall()]
                    cursor.execute(
                        """
                        INSERT INTO messages (conversation_id, role, content)
                        VALUES (%s, 'user', 'email=user@example.com'),
                               (%s, 'assistant', 'password=hunter2')
                        """,
                        tuple(conversations),
                    )

        assert _run("baseline", env).returncode == 0
        first_apply = _run("apply", env, "--target", "006")
        assert first_apply.returncode == 0
        assert "applied: 006_conversations_messages.sql" in first_apply.stdout
        assert "007_remove_raw_conversation_sessions.sql" not in first_apply.stdout

        with psycopg.connect(schema_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'conversations'
                          AND column_name = 'session_id'
                        """
                    )
                    assert cursor.fetchone()[0] == "YES"
                    cursor.execute(
                        """
                        INSERT INTO conversations (domain_id, channel, session_id)
                        VALUES (%s, 'whatsapp', 'legacy-after-expand')
                        """,
                        (domain_id,),
                    )
                    cursor.execute(
                        """
                        INSERT INTO conversations (
                          domain_id, channel, session_hash, session_hash_version
                        )
                        VALUES (%s, 'whatsapp', %s, 'hmac-sha256-v1')
                        ON CONFLICT (domain_id, channel, session_hash)
                          WHERE session_hash IS NOT NULL
                            AND status IN ('bot', 'handoff_pending', 'human_active')
                        DO UPDATE SET updated_at = now()
                        """,
                        (domain_id, "f" * 64),
                    )

        partial = _run_backfill(env, "--batch-size", "1", "--max-batches", "1")
        assert partial.returncode == 0
        assert "batches=1" in partial.stdout
        assert "remaining_conversations=0" not in partial.stdout
        changed_secret = _run_backfill(
            {**env, "PERSISTENCE_HASH_SECRET": "different-secret"}
        )
        assert changed_secret.returncode == 1
        assert "differs from the identity pinned" in changed_secret.stderr
        changed_version = _run_backfill(
            {**env, "PERSISTENCE_HASH_VERSION": "hmac-sha256-v2"}
        )
        assert changed_version.returncode == 1
        assert "differs from the identity pinned" in changed_version.stderr
        assert _run("apply", env).returncode == 1

        backfill = _run_backfill(env, "--batch-size", "1")
        assert backfill.returncode == 0
        assert "duplicates_merged=1" in backfill.stdout
        assert "contract_ready=false" in backfill.stdout
        assert _run("apply", env).returncode == 1

        with psycopg.connect(schema_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM conversations WHERE status = 'merged' LIMIT 1"
                    )
                    merged_conversation_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO messages (conversation_id, role, content)
                        VALUES (%s, 'user', 'token=late-legacy-secret')
                        """,
                        (merged_conversation_id,),
                    )
        late_legacy_message = _run_backfill(env)
        assert late_legacy_message.returncode == 0
        assert "messages=1" in late_legacy_message.stdout

        ready = _run_backfill(
            env,
            "--verify-contract-ready",
            "--quiet-period-seconds",
            "0",
        )
        assert ready.returncode == 0
        assert "contract_ready=true" in ready.stdout

        with psycopg.connect(schema_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO conversations (domain_id, channel, session_id)
                        VALUES (%s, 'whatsapp', 'legacy-after-expand')
                        """,
                        (domain_id,),
                    )

        assert _run("apply", env).returncode == 1
        assert (
            _run_backfill(
                env,
                "--verify-contract-ready",
                "--quiet-period-seconds",
                "0",
            ).returncode
            == 0
        )
        assert _run("apply", env).returncode == 0
        assert _run("verify", env).returncode == 0

        with psycopg.connect(schema_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      count(*) FILTER (
                        WHERE status IN ('bot', 'handoff_pending', 'human_active')
                      ),
                      count(*) FILTER (WHERE status = 'merged'),
                      min(session_hash),
                      min(session_hash_version)
                    FROM conversations
                    """
                )
                active_count, merged_count, session_hash, hash_version = cursor.fetchone()
                cursor.execute("SELECT string_agg(content, ' ') FROM messages")
                persisted_content = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM information_schema.columns
                      WHERE table_schema = current_schema()
                        AND table_name = 'conversations'
                        AND column_name = 'session_id'
                    )
                    """
                )
                has_raw_session_column = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT phase, contracted_at IS NOT NULL FROM conversation_privacy_rollout"
                )
                rollout_phase = cursor.fetchone()

        assert active_count == 3
        assert merged_count == 2
        assert len(session_hash) == 64
        assert hash_version == "hmac-sha256-v1"
        assert "user@example.com" not in persisted_content
        assert "hunter2" not in persisted_content
        assert has_raw_session_column is False
        assert rollout_phase == ("contracted", True)
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_fresh_database_requires_explicit_writer_confirmation_before_contract() -> None:
    assert DATABASE_URL
    import psycopg
    from psycopg.conninfo import make_conninfo

    schema = f"conversation_fresh_{uuid4().hex[:12]}"
    schema_url = make_conninfo(
        DATABASE_URL,
        options=f"-c search_path={schema},public",
    )
    env = {
        **os.environ,
        "DATABASE_URL": schema_url,
        "PERSISTENCE_HASH_SECRET": "fresh-database-secret",
        "PERSISTENCE_HASH_VERSION": "hmac-sha256-v1",
    }

    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
    try:
        assert _run("apply", env, "--target", "006").returncode == 0
        with psycopg.connect(schema_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT phase, contract_ready_at IS NOT NULL, contracted_at IS NOT NULL
                    FROM conversation_privacy_rollout
                    """
                )
                assert cursor.fetchone() == ("expanded", False, False)
                cursor.execute(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM information_schema.columns
                      WHERE table_schema = current_schema()
                        AND table_name = 'conversations'
                        AND column_name = 'session_id'
                    )
                    """
                )
                assert cursor.fetchone()[0] is True
                cursor.execute(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM pg_catalog.pg_tables
                      WHERE schemaname = current_schema()
                        AND tablename = 'schema_migrations'
                    )
                    """
                )
                assert cursor.fetchone()[0] is True

        assert _run("apply", env).returncode == 1
        assert (
            _run_backfill(
                env,
                "--verify-contract-ready",
                "--quiet-period-seconds",
                "0",
            ).returncode
            == 0
        )
        assert _run("apply", env).returncode == 0
        assert _run("verify", env).returncode == 0
        with psycopg.connect(schema_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT phase, contracted_at IS NOT NULL FROM conversation_privacy_rollout"
                )
                assert cursor.fetchone() == ("contracted", True)
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_baseline_rejects_missing_critical_index() -> None:
    assert DATABASE_URL
    import psycopg
    from psycopg.conninfo import make_conninfo

    schema = f"conversation_baseline_{uuid4().hex[:12]}"
    schema_url = make_conninfo(
        DATABASE_URL,
        options=f"-c search_path={schema},public",
    )
    env = {**os.environ, "DATABASE_URL": schema_url}

    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with psycopg.connect(schema_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    for name in ("001_initial_schema.sql", "002_web_auth.sql"):
                        cursor.execute((ROOT / "migrations" / name).read_text(encoding="utf-8"))
                    cursor.execute("DROP INDEX idx_messages_conversation_created")

        baseline = _run("baseline", env)
        assert baseline.returncode == 1
        assert "missing critical indexes" in baseline.stderr
        assert "idx_messages_conversation_created" in baseline.stderr
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _run(
    command: str,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.migrate", command, *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run_backfill(
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.backfill_conversation_privacy", *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
