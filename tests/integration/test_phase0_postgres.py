from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.db.runtime import DatabaseRuntime
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_QUEUED,
    PERSISTENCE_PERSISTED,
    OperationalRepository,
)
from app.api.schemas.feedback import FeedbackRequest
from app.conversations.service import ConversationHistoryService, hash_session
from app.integrations.webhook_ingress import CLAIMED, IN_PROGRESS, WebhookIngressRepository
from app.web_auth.models import OtpChallenge, VerifiedIdentity
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
                         support_cases, customer_preferences, customers,
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


def test_customer_identity_support_case_schema_is_expand_only(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    store = PostgresWebAuthStore(runtime)
    now = datetime.now(UTC)

    identity = store.save_identity(
        VerifiedIdentity(
            id="00000000-0000-0000-0000-000000000101",
            phone_hash="safe-phone-hash-customer",
            phone_last4="0101",
            verified_at=now,
            status="verified",
            customer_id=None,
        )
    )

    assert identity.customer_id is not None
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id::text, default_channel FROM customers WHERE id = %s",
                (identity.customer_id,),
            )
            assert cursor.fetchone() == (identity.customer_id, "whatsapp")
            cursor.execute(
                "SELECT id FROM domains WHERE name = 'suporte-vps-whatsapp'",
            )
            domain_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO customer_preferences (
                  customer_id, domain_id, preferences_json
                )
                VALUES (%s, %s, '{"locale":"pt-BR"}'::jsonb)
                RETURNING preferences_json
                """,
                (identity.customer_id, domain_id),
            )
            assert cursor.fetchone()[0]["locale"] == "pt-BR"
            cursor.execute(
                """
                INSERT INTO support_cases (
                  domain_id, customer_id, request_id, channel, reason_codes,
                  context_snapshot_sanitized, idempotency_key
                )
                VALUES (
                  %s, %s, 'req-support-case', 'web',
                  '["low_confidence"]'::jsonb,
                  '{"summary":"safe"}'::jsonb,
                  'support-case:req-support-case'
                )
                ON CONFLICT (idempotency_key)
                DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                RETURNING id, status, priority
                """,
                (domain_id, identity.customer_id),
            )
            support_case = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*)
                FROM support_cases
                WHERE idempotency_key = 'support-case:req-support-case'
                """
            )
            assert cursor.fetchone()[0] == 1

    assert support_case[1:] == ("open", "normal")


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


def test_persisted_turn_is_fanned_out_to_append_only_sink(
    runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ensure_domain(runtime)
    runtime.settings.enable_conversation_archive = True
    repository = OperationalRepository(runtime)

    result = repository.record_chat(
        ChatAuditInput(
            request_id="req-archive-fanout",
            domain="suporte-vps-whatsapp",
            session_id="whatsapp:archive-session",
            question="Meu email e user@example.com",
            answer="Nao use password=hunter2.",
            confidence=0.7,
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
                SELECT idempotency_key, status
                FROM operational_outbox
                WHERE event_type = 'conversation.turn.archived'
                """
            )
            outbox_rows = cursor.fetchall()

    assert outbox_rows == [(f"archive:{result.turn_id}", "pending")]

    sink_path = tmp_path / "archive.ndjson"
    monkeypatch.delenv("OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT", raising=False)
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "append_only_file")
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_PATH", str(sink_path))

    assert dispatch_one(DATABASE_URL) is True

    archived = [
        json.loads(line)
        for line in sink_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(archived) == 1
    record = archived[0]
    assert record["idempotency_key"] == f"archive:{result.turn_id}"
    assert record["event_type"] == "conversation.turn.archived"
    rendered = json.dumps(record)
    assert "archive-session" not in rendered
    assert "user@example.com" not in rendered
    assert "hunter2" not in rendered

    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status FROM operational_outbox
                WHERE event_type = 'conversation.turn.archived'
                """
            )
            assert cursor.fetchone()[0] == "delivered"


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


def test_customer_history_survives_logout_without_leaking_to_anonymous_session(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    customer_a = "00000000-0000-0000-0000-000000000201"
    customer_b = "00000000-0000-0000-0000-000000000202"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO customers (id, default_channel)
                VALUES (%s, 'web'), (%s, 'web')
                """,
                (customer_a, customer_b),
            )

    repository = OperationalRepository(runtime)

    def persist(question: str, customer_id: str | None) -> None:
        repository.record_chat(
            ChatAuditInput(
                request_id=f"req-{question.replace(' ', '-')}",
                domain="suporte-vps-whatsapp",
                session_id="same-public-session",
                customer_id=customer_id,
                question=question,
                answer=f"Resposta para {question}",
                confidence=0.8,
                escalated=False,
                handoff_reasons=[],
                references=["safe.md"],
                error_code=None,
                channel="web",
            )
        )

    persist("anon antes do login", None)
    persist("cliente a autenticado", customer_a)
    persist("anon depois do logout", None)
    persist("cliente b autenticado", customer_b)

    service = ConversationHistoryService(runtime)
    history_a = service.load_recent(
        domain="suporte-vps-whatsapp",
        channel="web",
        session_id="same-public-session",
        customer_id=customer_a,
        request_id="req-history-a",
    )
    anonymous_history = service.load_recent(
        domain="suporte-vps-whatsapp",
        channel="web",
        session_id="same-public-session",
        customer_id=None,
        request_id="req-history-anon",
    )
    history_b = service.load_recent(
        domain="suporte-vps-whatsapp",
        channel="web",
        session_id="same-public-session",
        customer_id=customer_b,
        request_id="req-history-b",
    )

    rendered_a = " ".join(message["content"] for message in history_a)
    rendered_anonymous = " ".join(message["content"] for message in anonymous_history)
    rendered_b = " ".join(message["content"] for message in history_b)

    assert "anon antes do login" in rendered_a
    assert "cliente a autenticado" in rendered_a
    assert "cliente b autenticado" not in rendered_a
    assert "cliente a autenticado" not in rendered_anonymous
    assert "anon depois do logout" in rendered_b
    assert "cliente b autenticado" in rendered_b
    assert "cliente a autenticado" not in rendered_b


def test_escalated_chat_creates_idempotent_support_case_and_handoff_outbox(
    runtime: DatabaseRuntime,
) -> None:
    _ensure_domain(runtime)
    customer_id = "00000000-0000-0000-0000-000000000301"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO customers (id, default_channel) VALUES (%s, 'web')",
                (customer_id,),
            )

    repository = OperationalRepository(runtime)
    audit = ChatAuditInput(
        request_id="req-support-case-handoff",
        domain="suporte-vps-whatsapp",
        session_id="support-case-session",
        customer_id=customer_id,
        question="Preciso falar com humano sobre acesso sensivel.",
        answer="Vou escalar para atendimento humano.",
        confidence=0.1,
        escalated=True,
        handoff_reasons=["explicit_human_request"],
        references=["safe.md"],
        error_code=None,
        channel="web",
    )

    first = repository.record_chat(audit)
    duplicate = repository.record_chat(audit)

    assert first.handoff_status == HANDOFF_QUEUED
    assert duplicate.handoff_status == HANDOFF_QUEUED
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, customer_id::text, request_id, reason_codes
                FROM support_cases
                WHERE request_id = 'req-support-case-handoff'
                """
            )
            support_cases = cursor.fetchall()
            cursor.execute(
                """
                SELECT payload_sanitized
                FROM operational_outbox
                WHERE request_id = 'req-support-case-handoff'
                """
            )
            outbox_rows = cursor.fetchall()

    assert len(support_cases) == 1
    support_case_id, persisted_customer_id, request_id, reason_codes = support_cases[0]
    assert persisted_customer_id == customer_id
    assert request_id == "req-support-case-handoff"
    assert reason_codes == ["explicit_human_request"]
    assert len(outbox_rows) == 1
    assert outbox_rows[0][0]["support_case_id"] == support_case_id


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
