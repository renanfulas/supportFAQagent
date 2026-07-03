"""Opt-in PostgreSQL coverage for the console read/metrics SQL.

The unit suites script fake cursors, which never exercise type inference or
Postgres-only constructs. This is where the class of bug documented in
``test_support_inbox_postgres.py`` (a bare NULL parameter rejected as
IndeterminateDatatype) would surface -- plus ``::uuid`` casts, ``AT TIME
ZONE``, ``jsonb_array_elements_text`` and ``percentile_cont``. Runs only when
``PHASE0_TEST_DATABASE_URL`` points at a disposable database.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.runtime import DatabaseRuntime
from app.support.metrics import SupportMetricsRepository
from app.support.repository import SupportCaseRepository


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)

TIMEZONE = "America/Sao_Paulo"


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


def _new_domain(cursor) -> tuple[str, str]:
    name = f"console-metrics-{uuid4().hex[:8]}"
    cursor.execute(
        "INSERT INTO domains (name, display_name) VALUES (%s, %s) RETURNING id",
        (name, "Console Metrics IT"),
    )
    return str(cursor.fetchone()[0]), name


def _new_staff(cursor, display_name: str = "Renan") -> str:
    staff_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO staff_members (id, phone_hash, phone_last4, display_name)
        VALUES (%s, %s, '0000', %s)
        """,
        (staff_id, f"hash-{staff_id}", display_name),
    )
    return staff_id


def _insert_case(
    cursor,
    domain_id: str,
    *,
    status: str = "open",
    priority: str = "normal",
    reason_codes: list[str] | None = None,
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
    assignee_staff_id: str | None = None,
) -> str:
    case_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO support_cases (
          id, domain_id, request_id, channel, status, priority,
          reason_codes, context_snapshot_sanitized, idempotency_key,
          assignee_staff_id, opened_at, closed_at
        )
        VALUES (%s, %s, %s, 'api', %s, %s, %s::jsonb, '{}'::jsonb, %s, %s,
                COALESCE(%s::timestamptz, now()), %s)
        """,
        (
            case_id,
            domain_id,
            f"req-{case_id}",
            status,
            priority,
            json.dumps(reason_codes or []),
            f"idem-{case_id}",
            assignee_staff_id,
            opened_at,
            closed_at,
        ),
    )
    return case_id


def _insert_event(
    cursor,
    case_id: str,
    actor_staff_id: str,
    action: str,
    from_status: str,
    to_status: str,
    created_at: datetime,
) -> None:
    cursor.execute(
        """
        INSERT INTO support_case_events (
          case_id, actor_staff_id, action, from_status, to_status, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (case_id, actor_staff_id, action, from_status, to_status, created_at),
    )


# --------------------------------------------------------------------------- #
# Fila ativa: filtro por assignee (::uuid) e waiting_seconds (ANY + interval)
# --------------------------------------------------------------------------- #


def test_list_active_cases_filters_and_computes_waiting_on_real_pg() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                domain_id, domain_name = _new_domain(cursor)
                staff_id = _new_staff(cursor)
                mine = _insert_case(
                    cursor,
                    domain_id,
                    status="waiting_customer",
                    assignee_staff_id=staff_id,
                    opened_at=datetime.now(UTC) - timedelta(hours=3),
                )
                _insert_case(cursor, domain_id, status="open")
                # Uma pausa fechada (30 min) para o caso do staff.
                _insert_event(
                    cursor, mine, staff_id, "wait_customer", "in_progress",
                    "waiting_customer", datetime.now(UTC) - timedelta(hours=2),
                )
                _insert_event(
                    cursor, mine, staff_id, "resume", "waiting_customer",
                    "in_progress", datetime.now(UTC) - timedelta(hours=1, minutes=30),
                )

        repository = SupportCaseRepository(runtime)

        # Sem filtro: dois casos do domain.
        unfiltered = repository.list_active_cases(
            domain=domain_name, status=None, cap=500
        )
        assert len(unfiltered.cases) == 2
        assert unfiltered.db_now is not None

        # Filtro ::uuid por assignee=me: so o caso do staff.
        filtered = repository.list_active_cases(
            domain=domain_name, status=None, cap=500, assignee_staff_id=staff_id
        )
        assert [c.case_id for c in filtered.cases] == [mine]
        assert filtered.cases[0].assignee_display_name == "Renan"
        # 30 min de pausa fechada acumulados.
        assert filtered.cases[0].waiting_seconds == pytest.approx(1800, abs=5)
    finally:
        runtime.close()


def test_get_case_waiting_seconds_open_pause_counts_to_now() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                domain_id, _ = _new_domain(cursor)
                staff_id = _new_staff(cursor)
                case_id = _insert_case(cursor, domain_id, status="waiting_customer")
                _insert_event(
                    cursor, case_id, staff_id, "wait_customer", "in_progress",
                    "waiting_customer", datetime.now(UTC) - timedelta(minutes=20),
                )

        repository = SupportCaseRepository(runtime)
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT now()")
                db_now = cursor.fetchone()[0]

        waiting = repository.get_case_waiting_seconds(case_id, db_now)
        # Pausa aberta conta ate now(): ~20 min.
        assert waiting == pytest.approx(1200, abs=30)
    finally:
        runtime.close()


# --------------------------------------------------------------------------- #
# Metricas: AT TIME ZONE, jsonb_array_elements_text, FILTER, percentile_cont
# --------------------------------------------------------------------------- #


def test_throughput_and_escalation_reasons_on_real_pg() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                domain_id, domain_name = _new_domain(cursor)
                _insert_case(
                    cursor, domain_id, reason_codes=["low_confidence"],
                    opened_at=datetime.now(UTC) - timedelta(days=1),
                )
                _insert_case(
                    cursor, domain_id,
                    reason_codes=["low_confidence", "sensitive_topic"],
                    status="closed",
                    opened_at=datetime.now(UTC) - timedelta(days=2),
                    closed_at=datetime.now(UTC) - timedelta(days=1),
                )

        metrics = SupportMetricsRepository(runtime)
        window_start = datetime.now(UTC) - timedelta(days=14)
        window_end = datetime.now(UTC)

        counts = metrics.get_throughput_counts(
            domain=domain_name,
            window_start=window_start,
            window_end=window_end,
            timezone_name=TIMEZONE,
        )
        total_opened = sum(day.get("opened", 0) for day in counts.values())
        total_closed = sum(day.get("closed", 0) for day in counts.values())
        assert total_opened == 2
        assert total_closed == 1

        reasons = metrics.get_escalation_reasons(
            domain=domain_name, window_start=window_start, window_end=window_end
        )
        as_dict = {r["reason_code"]: r["count"] for r in reasons}
        assert as_dict["low_confidence"] == 2
        assert as_dict["sensitive_topic"] == 1
    finally:
        runtime.close()


def test_feedback_metrics_matched_and_orphan_on_real_pg() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                domain_id, domain_name = _new_domain(cursor)
                audit_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO chat_audits (
                      id, request_id, domain_id, question_sanitized,
                      answer_sanitized, confidence, redaction_version
                    )
                    VALUES (%s, %s, %s, 'q', 'a', 0.9, 'v1')
                    """,
                    (audit_id, f"req-{audit_id}", domain_id),
                )
                # Dois matched (helpful/not) + um orphan.
                for helpful, audit in ((True, audit_id), (False, audit_id)):
                    cursor.execute(
                        """
                        INSERT INTO feedback (
                          chat_audit_id, helpful, source, context_status,
                          redaction_version
                        )
                        VALUES (%s, %s, 'web', 'matched', 'v1')
                        """,
                        (audit, helpful),
                    )
                cursor.execute(
                    """
                    INSERT INTO feedback (
                      helpful, source, context_status, redaction_version
                    )
                    VALUES (true, 'web', 'orphan', 'v1')
                    """
                )

        metrics = SupportMetricsRepository(runtime)
        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC) + timedelta(minutes=1)

        # Filtrado por domain: so os matched, orphan nao entra (sem domain).
        scoped = metrics.get_feedback_metrics(
            domain=domain_name, window_start=window_start, window_end=window_end
        )
        assert scoped == {"helpful": 1, "not_helpful": 1, "unknown_domain_count": 0}

        # Sem filtro: orphan conta em unknown_domain_count (>= 1 no banco
        # compartilhado desta sessao de testes).
        globally = metrics.get_feedback_metrics(
            domain=None, window_start=window_start, window_end=window_end
        )
        assert globally["unknown_domain_count"] >= 1
    finally:
        runtime.close()


def test_response_times_medians_on_real_pg() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                domain_id, domain_name = _new_domain(cursor)
                staff_id = _new_staff(cursor)
                opened = datetime.now(UTC) - timedelta(hours=2)
                case_id = _insert_case(
                    cursor, domain_id, status="closed",
                    opened_at=opened,
                    closed_at=opened + timedelta(hours=1),
                )
                # Primeira acao 10 min apos abrir.
                _insert_event(
                    cursor, case_id, staff_id, "claim", "open", "in_progress",
                    opened + timedelta(minutes=10),
                )

        metrics = SupportMetricsRepository(runtime)
        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC)

        times = metrics.get_response_times(
            domain=domain_name, window_start=window_start, window_end=window_end
        )
        assert times["median_seconds_to_first_action"] == pytest.approx(600, abs=30)
        assert times["median_seconds_to_close"] == pytest.approx(3600, abs=30)
    finally:
        runtime.close()


def test_response_times_null_when_window_empty() -> None:
    runtime = _open_runtime()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                _, domain_name = _new_domain(cursor)

        metrics = SupportMetricsRepository(runtime)
        # Janela no futuro: nenhum caso -> medianas null, nunca erro.
        window_start = datetime.now(UTC) + timedelta(days=1)
        window_end = datetime.now(UTC) + timedelta(days=2)
        times = metrics.get_response_times(
            domain=domain_name, window_start=window_start, window_end=window_end
        )
        assert times == {
            "median_seconds_to_first_action": None,
            "median_seconds_to_close": None,
        }
    finally:
        runtime.close()
