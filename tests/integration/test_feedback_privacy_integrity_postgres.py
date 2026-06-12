from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.api.schemas.feedback import FeedbackRequest
from app.conversations.service import hash_session
from app.db.operational import (
    ChatAuditInput,
    FeedbackIntegrityConflictError,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime


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
    assert result.returncode == 0, "Phase 0 migrations failed in disposable test database"


@pytest.fixture
def runtime() -> DatabaseRuntime:
    assert DATABASE_URL
    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="memory",
        enable_outbox_ingress=False,
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
        persistence_hash_secret="feedback-integrity-secret",
        persistence_hash_version="hmac-sha256-v1",
        conversation_history_messages=4,
    )
    database_runtime = DatabaseRuntime(settings)
    database_runtime.open()
    with database_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE messages, conversations, operational_outbox,
                         feedback, chat_audits
                RESTART IDENTITY CASCADE
                """
            )
    yield database_runtime
    database_runtime.close()


def test_feedback_isolated_by_session_and_sessionless_fallback_is_unambiguous(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)
    _record_chat(repository, request_id="req-shared", session_id="session-a", question="A")
    _record_chat(repository, request_id="req-shared", session_id="session-b", question="B")

    same_session = repository.record_feedback(
        FeedbackRequest(
            request_id="req-shared",
            session_id="session-a",
            helpful=True,
            reason="Minha senha \u00e9 feedback-secret",
            comment="token=feedback-token",
            source="web",
        )
    )
    wrong_session = repository.record_feedback(
        FeedbackRequest(
            request_id="req-shared",
            session_id="session-c",
            helpful=False,
            source="web",
        )
    )
    ambiguous_internal = repository.record_feedback(
        FeedbackRequest(
            request_id="req-shared",
            helpful=False,
            source="n8n",
        )
    )

    assert same_session.status == "matched"
    assert wrong_session.status == "orphan"
    assert ambiguous_internal.status == "orphan"

    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.context_status, f.session_hash, a.session_hash,
                       f.reason, f.comment_sanitized,
                       f.session_hash_version, a.session_hash_version
                FROM feedback f
                LEFT JOIN chat_audits a ON a.id = f.chat_audit_id
                """
            )
            rows = cursor.fetchall()

    session_a_hash = hash_session("session-a", "feedback-integrity-secret")
    session_c_hash = hash_session("session-c", "feedback-integrity-secret")
    rows_by_feedback_session = {row[1]: row for row in rows}
    assert rows_by_feedback_session[session_a_hash][0:3] == (
        "matched",
        session_a_hash,
        session_a_hash,
    )
    assert rows_by_feedback_session[session_a_hash][5:7] == (
        "hmac-sha256-v1",
        "hmac-sha256-v1",
    )
    assert "feedback-secret" not in str(rows_by_feedback_session[session_a_hash])
    assert "feedback-token" not in str(rows_by_feedback_session[session_a_hash])
    assert rows_by_feedback_session[session_c_hash][0:3] == (
        "orphan",
        session_c_hash,
        None,
    )
    assert rows_by_feedback_session[None][0:3] == ("orphan", None, None)


def test_internal_feedback_without_session_matches_unique_request(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)
    _record_chat(
        repository,
        request_id="req-globally-unique",
        session_id="session-a",
        question="Unique",
    )

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-globally-unique",
            helpful=True,
            source="n8n",
        )
    )

    assert response.status == "matched"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.session_hash, a.request_id
                FROM feedback f
                JOIN chat_audits a ON a.id = f.chat_audit_id
                WHERE f.request_id = 'req-globally-unique'
                """
            )
            assert cursor.fetchone() == (None, "req-globally-unique")


def test_feedback_is_orphan_when_request_is_reused_inside_same_session(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)
    _record_chat(
        repository,
        request_id="req-same-session-reused",
        session_id="session-a",
        question="First",
    )
    _record_chat(
        repository,
        request_id="req-same-session-reused",
        session_id="session-a",
        question="Second",
    )

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-same-session-reused",
            session_id="session-a",
            helpful=True,
            source="web",
        )
    )

    assert response.status == "orphan"


def test_feedback_message_id_is_persisted_and_retry_is_idempotent(
    runtime: DatabaseRuntime,
) -> None:
    repository = OperationalRepository(runtime)
    payload = FeedbackRequest(
        message_id="evolution-message-1",
        helpful=True,
        reason="resolved",
        source="n8n",
    )

    first = repository.record_feedback(payload)
    second = repository.record_feedback(payload)

    assert first.feedback_id == second.feedback_id
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*), min(message_id), min(idempotency_key),
                       min(feedback_fingerprint)
                FROM feedback
                WHERE message_id = 'evolution-message-1'
                """
            )
            count, message_id, idempotency_key, feedback_fingerprint = cursor.fetchone()
    assert count == 1
    assert message_id == "evolution-message-1"
    assert idempotency_key
    assert feedback_fingerprint


def test_feedback_message_id_reuse_with_different_payload_is_rejected(
    runtime: DatabaseRuntime,
) -> None:
    repository = OperationalRepository(runtime)
    repository.record_feedback(
        FeedbackRequest(
            message_id="evolution-message-conflict",
            helpful=True,
            source="n8n",
        )
    )

    with pytest.raises(FeedbackIntegrityConflictError):
        repository.record_feedback(
            FeedbackRequest(
                message_id="evolution-message-conflict",
                helpful=False,
                source="n8n",
            )
        )

    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*), bool_and(helpful)
                FROM feedback
                WHERE message_id = 'evolution-message-conflict'
                """
            )
            assert cursor.fetchone() == (1, True)


def test_migration_008_keeps_legacy_writers_compatible(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM domains WHERE name = 'suporte-vps-whatsapp'"
            )
            domain_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO chat_audits (
                  request_id, domain_id, session_hash, question_sanitized,
                  answer_sanitized, confidence, escalated, redaction_version
                )
                VALUES (
                  'legacy-writer-request', %s, 'legacy-session-hash',
                  'question', 'answer', 0.5, false, 'phase0-v1'
                )
                RETURNING id, session_hash_version
                """,
                (domain_id,),
            )
            audit_id, audit_hash_version = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO feedback (
                  request_id, chat_audit_id, session_hash, helpful, source,
                  context_status, redaction_version
                )
                VALUES (
                  'legacy-writer-request', %s, 'legacy-session-hash', true,
                  'api', 'matched', 'phase0-v1'
                )
                RETURNING session_hash_version
                """,
                (audit_id,),
            )
            feedback_hash_version = cursor.fetchone()[0]

    assert audit_hash_version == "legacy-unversioned"
    assert feedback_hash_version == "legacy-unversioned"


def _record_chat(
    repository: OperationalRepository,
    *,
    request_id: str,
    session_id: str,
    question: str,
) -> None:
    result = repository.record_chat(
        ChatAuditInput(
            request_id=request_id,
            domain="suporte-vps-whatsapp",
            session_id=session_id,
            question=question,
            answer="Resposta segura.",
            confidence=0.8,
            escalated=False,
            handoff_reasons=[],
            references=["safe.md"],
            error_code=None,
            channel="web",
        )
    )
    assert result.persistence_status == "persisted"


def _ensure_domain(runtime: DatabaseRuntime) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO domains (name, display_name)
                VALUES ('suporte-vps-whatsapp', 'Suporte VPS e WhatsApp')
                ON CONFLICT (name) DO NOTHING
                """
            )
