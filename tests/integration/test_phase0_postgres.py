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
from app.integrations.webhook_ingress import CLAIMED, IN_PROGRESS, WebhookIngressRepository
from app.web_auth.models import OtpChallenge
from app.web_auth.storage import PostgresWebAuthStore
from scripts.dispatch_outbox import PermanentDeliveryError, dispatch_one


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
    )
    database_runtime = DatabaseRuntime(settings)
    database_runtime.open()
    with database_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE webhook_ingress_receipts, operational_outbox,
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
