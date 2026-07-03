from __future__ import annotations

import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.runtime import DatabaseRuntime
from app.support.transitions import InvalidTransition, SupportCaseTransitionService


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


def _open_runtime() -> DatabaseRuntime:
    assert DATABASE_URL
    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="disabled",
        enable_outbox_ingress=False,
        session_domain_store_backend="memory",
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=2,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
    )
    runtime = DatabaseRuntime(settings)
    runtime.open()
    return runtime


@pytest.fixture
def seeded_case():
    """Insert a disposable domain + support_case(open) + two staff members."""

    runtime = _open_runtime()
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            domain_name = f"console-it-{uuid4().hex[:8]}"
            cursor.execute(
                "INSERT INTO domains (name, display_name) VALUES (%s, %s) RETURNING id",
                (domain_name, "Console Integration Test"),
            )
            domain_id = cursor.fetchone()[0]

            case_id = str(uuid4())
            cursor.execute(
                """
                INSERT INTO support_cases (
                  id, domain_id, request_id, channel, status, priority,
                  reason_codes, context_snapshot_sanitized, idempotency_key
                )
                VALUES (%s, %s, %s, 'api', 'open', 'normal', '[]'::jsonb, '{}'::jsonb, %s)
                """,
                (case_id, domain_id, f"req-{case_id}", f"idem-{case_id}"),
            )

            staff_ids = []
            for name in ("Staff A", "Staff B"):
                staff_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO staff_members (id, phone_hash, phone_last4, display_name)
                    VALUES (%s, %s, '0000', %s)
                    """,
                    (staff_id, f"hash-{staff_id}", name),
                )
                staff_ids.append(staff_id)
    yield case_id, staff_ids[0], staff_ids[1]
    runtime.close()


def test_concurrent_claims_exactly_one_wins(seeded_case) -> None:
    case_id, staff_a, staff_b = seeded_case
    runtime_a = _open_runtime()
    runtime_b = _open_runtime()
    barrier = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def _claim(name: str, runtime: DatabaseRuntime, actor_staff_id: str) -> None:
        service = SupportCaseTransitionService(runtime)
        barrier.wait(timeout=5)
        try:
            outcomes[name] = service.apply(
                case_id=case_id,
                action="claim",
                actor_staff_id=actor_staff_id,
                note=None,
            )
        except InvalidTransition as exc:
            outcomes[name] = exc

    thread_a = threading.Thread(target=_claim, args=("a", runtime_a, staff_a))
    thread_b = threading.Thread(target=_claim, args=("b", runtime_b, staff_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)
    runtime_a.close()
    runtime_b.close()

    results = [outcomes["a"], outcomes["b"]]
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0].to_status == "in_progress"
    assert winners[0].assignee_staff_id in {staff_a, staff_b}
    # O perdedor ve o estado ja vencido pelo outro operador (nao "open").
    assert losers[0].status == "in_progress"

    # Evento auditavel gravado uma unica vez -- so o UPDATE vencedor insere.
    verify_runtime = _open_runtime()
    with verify_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM support_case_events WHERE case_id = %s AND action = 'claim'",
                (case_id,),
            )
            assert cursor.fetchone()[0] == 1
    verify_runtime.close()


def test_full_matrix_round_trip_and_closed_at_constraint(seeded_case) -> None:
    case_id, staff_a, _staff_b = seeded_case
    runtime = _open_runtime()
    service = SupportCaseTransitionService(runtime)
    try:
        claimed = service.apply(
            case_id=case_id, action="claim", actor_staff_id=staff_a, note=None
        )
        assert claimed.to_status == "in_progress"

        waiting = service.apply(
            case_id=case_id,
            action="wait_customer",
            actor_staff_id=staff_a,
            note="aguardando retorno do cliente",
        )
        assert waiting.to_status == "waiting_customer"

        resumed = service.apply(
            case_id=case_id, action="resume", actor_staff_id=staff_a, note=None
        )
        assert resumed.to_status == "in_progress"

        closed = service.apply(
            case_id=case_id, action="close", actor_staff_id=staff_a, note="resolvido"
        )
        assert closed.to_status == "closed"

        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, closed_at FROM support_cases WHERE id = %s",
                    (case_id,),
                )
                status, closed_at = cursor.fetchone()
                assert status == "closed"
                assert closed_at is not None

                cursor.execute(
                    """
                    SELECT action, from_status, to_status
                    FROM support_case_events
                    WHERE case_id = %s
                    ORDER BY created_at ASC
                    """,
                    (case_id,),
                )
                actions = [row[0] for row in cursor.fetchall()]
                assert actions == ["claim", "wait_customer", "resume", "close"]
    finally:
        runtime.close()


def test_invalid_action_from_terminal_status_is_rejected(seeded_case) -> None:
    case_id, staff_a, _staff_b = seeded_case
    runtime = _open_runtime()
    service = SupportCaseTransitionService(runtime)
    try:
        service.apply(case_id=case_id, action="claim", actor_staff_id=staff_a, note=None)
        service.apply(case_id=case_id, action="close", actor_staff_id=staff_a, note=None)

        with pytest.raises(InvalidTransition) as exc_info:
            service.apply(
                case_id=case_id, action="claim", actor_staff_id=staff_a, note=None
            )
        assert exc_info.value.status == "closed"
    finally:
        runtime.close()
