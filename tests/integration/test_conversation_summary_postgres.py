from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.conversations.summary import run_summary_batch


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    if not DATABASE_URL:
        return
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "apply"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "migrations failed in disposable test database"


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_answer(self, prompt: str) -> str:
        return self.response


def _connect():
    import psycopg

    return psycopg.connect(DATABASE_URL)


def _seed_conversation(connection, *, name: str, n_messages: int, hours_old: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO domains (name, display_name) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id",
            (name, name),
        )
        domain_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO conversations
              (domain_id, channel, session_hash, session_hash_version, status, last_message_at)
            VALUES (%s, 'whatsapp', %s, 'hmac-sha256-v1', 'bot', now() - make_interval(hours => %s))
            RETURNING id
            """,
            (domain_id, f"hash-{name}", hours_old),
        )
        conv_id = cursor.fetchone()[0]
        for i in range(n_messages):
            role = "user" if i % 2 == 0 else "assistant"
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, redaction_version) "
                "VALUES (%s, %s, %s, 'phase0-v1')",
                (conv_id, role, f"mensagem {i}"),
            )
    connection.commit()
    return str(conv_id)


def test_summary_batch_writes_and_is_idempotent() -> None:
    # Assertions are scoped to the seeded conversation_key so other integration
    # tests sharing the database never interfere.
    provider = _FakeProvider('{"problem":"vps caiu","solution":"reiniciada","status":"resolvido"}')
    with _connect() as connection:
        conv_id = _seed_conversation(connection, name="itest-sum-a", n_messages=2, hours_old=48)

        run_summary_batch(connection, provider, model="test-model", inactivity_hours=24, min_turns=2, limit=100)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT problem, status, source_turn_count FROM conversation_summaries WHERE conversation_key = %s",
                (conv_id,),
            )
            assert cursor.fetchone() == ("vps caiu", "resolvido", 2)

        # Re-run is idempotent: the conversation is already summarized, so it stays
        # exactly one row (and the UNIQUE constraint would reject a duplicate).
        stats2 = run_summary_batch(connection, provider, model="test-model", inactivity_hours=24, min_turns=2, limit=100)
        assert stats2["errors"] == 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM conversation_summaries WHERE conversation_key = %s", (conv_id,))
            assert cursor.fetchone()[0] == 1


def test_summary_batch_skips_trivial_single_turn() -> None:
    provider = _FakeProvider('{"problem":"x","solution":"y","status":"resolvido"}')
    with _connect() as connection:
        conv_id = _seed_conversation(connection, name="itest-sum-b", n_messages=1, hours_old=48)
        run_summary_batch(connection, provider, model="test-model", inactivity_hours=24, min_turns=2, limit=100)
        # The single-turn conversation must not be summarized.
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM conversation_summaries WHERE conversation_key = %s", (conv_id,))
            assert cursor.fetchone()[0] == 0
