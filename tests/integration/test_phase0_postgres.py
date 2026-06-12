from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.db.runtime import DatabaseRuntime
from app.db.operational import (
    ChatAuditInput,
    PERSISTENCE_PERSISTED,
    OperationalRepository,
)
from app.api.schemas.feedback import FeedbackRequest
from app.conversations.service import ConversationHistoryService, hash_session
from app.integrations.webhook_ingress import CLAIMED, IN_PROGRESS, WebhookIngressRepository
from app.web_auth.models import OtpChallenge
from app.web_auth.storage import PostgresWebAuthStore
from scripts.dispatch_outbox import PermanentDeliveryError, dispatch_one
from scripts.prune_operational_data import prune_batch


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
        web_auth_storage_backend="postgres",
        enable_outbox_ingress=True,
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=8,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
        persistence_hash_secret="integration-persistence-secret",
        persistence_hash_version="hmac-sha256-v1",
        conversation_history_messages=4,
    )
    database_runtime = DatabaseRuntime(settings)
    database_runtime.open()
    with database_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE messages, conversations,
                         webhook_ingress_receipts, operational_outbox,
                         feedback, chat_audits, otp_challenges,
                         web_sessions, verified_identities
                RESTART IDENTITY CASCADE
                """
            )
    yield database_runtime
    database_runtime.close()


def test_otp_can_be_consumed_only_once(runtime: DatabaseRuntime) -> None:
    store = PostgresWebAuthStore(runtime)
    now = datetime.now(UTC)
    challenge = OtpChallenge(
        id="00000000-0000-0000-0000-000000000001",
        phone_hash="safe-phone-hash",
        phone_last4="0000",
        code_digest="correct-digest",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        attempts_remaining=5,
        status="pending",
    )
    store.save_challenge(challenge)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: store.consume_challenge(challenge.id, "correct-digest", now),
                range(2),
            )
        )

    assert sum(result is not None for result in results) == 1


def test_two_dispatchers_deliver_one_event_once(
    runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deliveries: list[str] = []
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operational_outbox (
                  event_type, idempotency_key, request_id, payload_sanitized
                )
                VALUES ('handoff.requested', 'handoff:concurrent', 'req-concurrent', '{}'::jsonb)
                """
            )

    def deliver_once(event: dict) -> None:
        deliveries.append(str(event["idempotency_key"]))
        time.sleep(0.2)

    monkeypatch.setattr("scripts.dispatch_outbox.deliver", deliver_once)
    with ThreadPoolExecutor(max_workers=2) as executor:
        processed = list(executor.map(lambda _: dispatch_one(DATABASE_URL), range(2)))

    assert deliveries == ["handoff:concurrent"]
    assert sorted(processed) == [False, True]


def test_dispatcher_moves_fifth_failure_to_dead_letter(
    runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operational_outbox (
                  event_type, idempotency_key, request_id, payload_sanitized, attempt_count
                )
                VALUES ('handoff.requested', 'handoff:dead', 'req-dead', '{}'::jsonb, 4)
                """
            )
    monkeypatch.setattr(
        "scripts.dispatch_outbox.deliver",
        lambda event: (_ for _ in ()).throw(TimeoutError("transient")),
    )

    assert dispatch_one(DATABASE_URL) is True

    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, attempt_count, last_error_code FROM operational_outbox WHERE idempotency_key = 'handoff:dead'"
            )
            assert cursor.fetchone() == ("dead_letter", 5, "delivery_failed")


def test_dispatcher_moves_permanent_rejection_directly_to_dead_letter(
    runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operational_outbox (
                  event_type, idempotency_key, request_id, payload_sanitized
                )
                VALUES ('handoff.requested', 'handoff:permanent', 'req-permanent', '{}'::jsonb)
                """
            )
    monkeypatch.setattr(
        "scripts.dispatch_outbox.deliver",
        lambda event: (_ for _ in ()).throw(PermanentDeliveryError("rejected")),
    )

    assert dispatch_one(DATABASE_URL) is True

    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, attempt_count, last_error_code FROM operational_outbox WHERE idempotency_key = 'handoff:permanent'"
            )
            assert cursor.fetchone() == ("dead_letter", 1, "permanent_delivery_failed")


def test_ingress_claim_is_persistently_idempotent(runtime: DatabaseRuntime) -> None:
    repository = WebhookIngressRepository(runtime)

    def claim():
        return repository.claim(
            event_type="handoff.requested",
            idempotency_key="handoff:ingress",
            request_id="req-ingress",
            body_hash="same-hash",
        ).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: claim(), range(2)))

    assert sorted(statuses) == sorted([CLAIMED, IN_PROGRESS])
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT idempotency_key_hash FROM webhook_ingress_receipts")
            stored_key = cursor.fetchone()[0]
    assert stored_key != "handoff:ingress"
    assert len(stored_key) == 64


def test_ingress_rejects_same_key_for_different_event_type(runtime: DatabaseRuntime) -> None:
    repository = WebhookIngressRepository(runtime)
    first = repository.claim(
        event_type="handoff.requested",
        idempotency_key="shared:key",
        request_id="req-one",
        body_hash="same-hash",
    )
    second = repository.claim(
        event_type="otp.delivery.requested",
        idempotency_key="shared:key",
        request_id="req-two",
        body_hash="same-hash",
    )

    assert first.status == CLAIMED
    assert second.status == "payload_conflict"


def test_retention_preserves_audit_linked_to_recent_feedback(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_audits (
                  request_id, domain_id, question_sanitized, answer_sanitized,
                  confidence, redaction_version, created_at
                )
                SELECT request_id, id, 'safe question', 'safe answer',
                       0.8, 'phase0-v1', now() - INTERVAL '90 days'
                FROM domains
                CROSS JOIN (
                  VALUES ('req-recent-feedback'), ('req-expired-feedback')
                ) AS requests(request_id)
                WHERE name = 'suporte-vps-whatsapp'
                """
            )
            cursor.execute(
                """
                INSERT INTO feedback (
                  request_id, chat_audit_id, helpful, source, context_status,
                  redaction_version, created_at
                )
                SELECT
                  request_id,
                  id,
                  true,
                  'integration',
                  'matched',
                  'phase0-v1',
                  CASE
                    WHEN request_id = 'req-recent-feedback' THEN now()
                    ELSE now() - INTERVAL '90 days'
                  END
                FROM chat_audits
                WHERE request_id IN ('req-recent-feedback', 'req-expired-feedback')
                """
            )
            counts = prune_batch(
                cursor,
                conversation_days=60,
                otp_days=7,
                outbox_delivered_days=30,
                receipt_days=30,
                batch_size=100,
                dry_run=False,
            )
            cursor.execute(
                """
                SELECT f.request_id, f.context_status, a.request_id
                FROM feedback AS f
                LEFT JOIN chat_audits AS a ON a.id = f.chat_audit_id
                ORDER BY f.request_id
                """
            )
            remaining_feedback = cursor.fetchall()
            cursor.execute(
                """
                SELECT request_id
                FROM chat_audits
                ORDER BY request_id
                """
            )
            remaining_audits = cursor.fetchall()

    assert counts["feedback"] == 1
    assert counts["chat_audits"] == 1
    assert remaining_feedback == [
        ("req-recent-feedback", "matched", "req-recent-feedback")
    ]
    assert remaining_audits == [("req-recent-feedback",)]


def test_conversation_schema_removes_raw_session_and_persists_only_sanitized_messages(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)

    result = repository.record_chat(
        ChatAuditInput(
            request_id="req-conversation-sanitized",
            domain="suporte-vps-whatsapp",
            session_id="whatsapp:raw-customer-session",
            question="Meu IP e 192.0.2.10 e email user@example.com",
            answer="Nao use password=hunter2.",
            confidence=0.8,
            escalated=False,
            handoff_reasons=[],
            references=["safe.md"],
            error_code=None,
            channel="whatsapp",
        )
    )

    assert result.persistence_status == PERSISTENCE_PERSISTED
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'conversations'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT c.session_hash, c.channel, m.content, m.redaction_version
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
                ORDER BY m.created_at, m.role DESC
                """
            )
            rows = cursor.fetchall()

    assert "session_id" not in columns
    assert len(rows) == 2
    rendered = str(rows)
    assert "raw-customer-session" not in rendered
    assert "192.0.2.10" not in rendered
    assert "user@example.com" not in rendered
    assert "hunter2" not in rendered
    assert all(row[1] == "whatsapp" for row in rows)
    assert all(row[3] == "phase0-v1" for row in rows)


def test_conversation_turn_is_persistently_idempotent_and_request_reuse_is_visible(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)
    base = ChatAuditInput(
        request_id="req-shared",
        domain="suporte-vps-whatsapp",
        session_id="session-idempotent",
        question="Como reiniciar o nginx?",
        answer="Use o procedimento seguro.",
        confidence=0.8,
        escalated=False,
        handoff_reasons=[],
        references=["nginx.md"],
        error_code=None,
    )

    first = repository.record_chat(base)
    duplicate = repository.record_chat(
        ChatAuditInput(**{**base.__dict__, "turn_id": "00000000-0000-0000-0000-000000000099"})
    )
    reused = repository.record_chat(
        ChatAuditInput(
            **{
                **base.__dict__,
                "turn_id": "00000000-0000-0000-0000-000000000100",
                "question": "Como verificar o Apache?",
            }
        )
    )

    assert first.turn_id == duplicate.turn_id
    assert duplicate.request_id_reused is False
    assert reused.request_id_reused is True
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM chat_audits WHERE request_id = 'req-shared'")
            assert cursor.fetchone()[0] == 2
            cursor.execute("SELECT count(*) FROM messages WHERE request_id = 'req-shared'")
            assert cursor.fetchone()[0] == 4


def test_feedback_treats_reused_request_id_as_orphan(runtime: DatabaseRuntime) -> None:
    _ensure_domain(runtime)
    repository = OperationalRepository(runtime)
    for index in range(2):
        repository.record_chat(
            ChatAuditInput(
                request_id="req-ambiguous-feedback",
                domain="suporte-vps-whatsapp",
                session_id="session-feedback",
                question=f"Pergunta distinta {index}",
                answer=f"Resposta {index}",
                confidence=0.8,
                escalated=False,
                handoff_reasons=[],
                references=[f"safe-{index}.md"],
                error_code=None,
            )
        )

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-ambiguous-feedback",
            helpful=True,
            source="integration",
        )
    )

    assert response.status == "orphan"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT chat_audit_id, context_status
                FROM feedback
                WHERE request_id = 'req-ambiguous-feedback'
                """
            )
            assert cursor.fetchone() == (None, "orphan")


def test_concurrent_turns_share_one_active_conversation_and_history_is_ordered(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)

    def persist(index: int):
        return OperationalRepository(runtime).record_chat(
            ChatAuditInput(
                request_id=f"req-concurrent-conversation-{index}",
                domain="suporte-vps-whatsapp",
                session_id="same-session",
                question=f"Pergunta {index}",
                answer=f"Resposta {index}",
                confidence=0.8,
                escalated=False,
                handoff_reasons=[],
                references=["safe.md"],
                error_code=None,
                channel="whatsapp",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(persist, range(2)))

    assert all(result.persistence_status == PERSISTENCE_PERSISTED for result in results)
    history = ConversationHistoryService(runtime).load_recent(
        domain="suporte-vps-whatsapp",
        channel="whatsapp",
        session_id="same-session",
        request_id="req-history",
    )
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM conversations c
                JOIN domains d ON d.id = c.domain_id
                WHERE d.name = 'suporte-vps-whatsapp'
                  AND c.channel = 'whatsapp'
                  AND c.session_hash = %s
                  AND c.status IN ('bot', 'handoff_pending', 'human_active')
                """,
                (hash_session("same-session", "integration-persistence-secret"),),
            )
            assert cursor.fetchone()[0] == 1

    assert len(history) == 4
    assert [message["role"] for message in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


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
