"""Repository-level coverage for the Fase B console additions: dono do caso
(assignee join), tempo pausado real (``waiting_seconds`` a partir de
``support_case_events``) e o historico de eventos servido no detalhe.

Uses the same scripted fake cursor pattern as ``tests/test_support_inbox.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.support.repository import SupportCaseRepository


DB_NOW = datetime(2026, 7, 3, 18, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, fetchone_results: list, fetchall_results: list) -> None:
        self._fetchone = list(fetchone_results)
        self._fetchall = list(fetchall_results)
        self.executed: list[tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone.pop(0)

    def fetchall(self):
        return self._fetchall.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._connection = FakeConnection(cursor)

    @contextmanager
    def transaction(self):
        yield self._connection


def _active_row(
    case_id: str,
    *,
    status: str = "in_progress",
    opened_at: datetime,
    assignee_staff_id: str | None = None,
    assignee_display_name: str | None = None,
) -> tuple:
    return (
        case_id,
        "suporte-vps-whatsapp",
        status,
        "normal",
        "whatsapp",
        f"req-{case_id}",
        [],
        {},
        opened_at,
        opened_at,
        assignee_staff_id,
        assignee_display_name,
        DB_NOW,
    )


# --------------------------------------------------------------------------- #
# Dono do caso na fila e no historico
# --------------------------------------------------------------------------- #


def test_list_active_cases_joins_assignee_display_name() -> None:
    rows = [
        _active_row(
            "case-1",
            opened_at=DB_NOW - timedelta(hours=1),
            assignee_staff_id="staff-1",
            assignee_display_name="Renan",
        )
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    active = repository.list_active_cases(domain=None, status=None, cap=500)

    assert active.cases[0].assignee_staff_id == "staff-1"
    assert active.cases[0].assignee_display_name == "Renan"


def test_list_active_cases_unassigned_case_has_no_assignee() -> None:
    rows = [_active_row("case-1", opened_at=DB_NOW - timedelta(hours=1))]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    active = repository.list_active_cases(domain=None, status=None, cap=500)

    assert active.cases[0].assignee_staff_id is None
    assert active.cases[0].assignee_display_name is None
    assert active.cases[0].waiting_seconds == 0.0


def test_list_active_cases_with_no_rows_skips_waiting_seconds_query() -> None:
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[[]])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    active = repository.list_active_cases(domain=None, status=None, cap=500)

    assert active.cases == []
    assert active.db_now is None
    # So a query da fila; a de waiting_seconds nem roda sem casos.
    assert len(cursor.executed) == 1


def test_list_active_cases_filters_by_assignee_staff_id() -> None:
    rows = [
        _active_row(
            "case-1",
            opened_at=DB_NOW - timedelta(hours=1),
            assignee_staff_id="staff-1",
            assignee_display_name="Renan",
        )
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    repository.list_active_cases(
        domain=None, status=None, cap=500, assignee_staff_id="staff-1"
    )

    _, params = cursor.executed[0]
    assert "staff-1" in params


def test_list_history_cases_joins_assignee_and_skips_waiting_query() -> None:
    row = (
        "case-1",
        "suporte-vps-whatsapp",
        "closed",
        "normal",
        "whatsapp",
        "req-1",
        [],
        {},
        DB_NOW - timedelta(days=1),
        DB_NOW,
        "staff-1",
        "Renan",
    )
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[[row]])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    cases = repository.list_history_cases(domain=None, status=None, limit=25, offset=0)

    assert cases[0].assignee_display_name == "Renan"
    assert cases[0].waiting_seconds == 0.0
    # Historico nao passa por SLA: nenhuma consulta extra de eventos.
    assert len(cursor.executed) == 1


# --------------------------------------------------------------------------- #
# waiting_seconds: soma de intervalos wait_customer -> resume
# --------------------------------------------------------------------------- #


def test_list_active_cases_sums_closed_pause_intervals() -> None:
    opened_at = DB_NOW - timedelta(hours=5)
    rows = [_active_row("case-1", opened_at=opened_at)]
    events = [
        ("case-1", "wait_customer", DB_NOW - timedelta(hours=3)),
        ("case-1", "resume", DB_NOW - timedelta(hours=2, minutes=30)),  # 30 min
        ("case-1", "wait_customer", DB_NOW - timedelta(hours=1)),
        ("case-1", "resume", DB_NOW - timedelta(minutes=50)),  # 10 min
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows, events])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    active = repository.list_active_cases(domain=None, status=None, cap=500)

    assert active.cases[0].waiting_seconds == 40 * 60


def test_list_active_cases_open_pause_counts_through_db_now() -> None:
    opened_at = DB_NOW - timedelta(hours=2)
    rows = [_active_row("case-1", status="waiting_customer", opened_at=opened_at)]
    events = [("case-1", "wait_customer", DB_NOW - timedelta(minutes=40))]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows, events])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    active = repository.list_active_cases(domain=None, status=None, cap=500)

    assert active.cases[0].waiting_seconds == 40 * 60


def test_get_case_waiting_seconds_for_single_case() -> None:
    events = [
        ("case-1", "wait_customer", DB_NOW - timedelta(minutes=20)),
        ("case-1", "resume", DB_NOW - timedelta(minutes=5)),
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[events])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    waiting_seconds = repository.get_case_waiting_seconds("case-1", DB_NOW)

    assert waiting_seconds == 15 * 60


def test_get_case_waiting_seconds_with_no_events_is_zero() -> None:
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[[]])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    assert repository.get_case_waiting_seconds("case-1", DB_NOW) == 0.0


# --------------------------------------------------------------------------- #
# Historico de eventos (detalhe)
# --------------------------------------------------------------------------- #


def test_get_case_events_maps_rows_oldest_first() -> None:
    rows = [
        (
            "claim",
            "open",
            "in_progress",
            None,
            "Renan",
            DB_NOW - timedelta(hours=2),
        ),
        (
            "close",
            "in_progress",
            "closed",
            "resolvido no telefone",
            "Renan",
            DB_NOW - timedelta(hours=1),
        ),
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    events = repository.get_case_events("case-1")

    assert [event.action for event in events] == ["claim", "close"]
    assert events[1].note == "resolvido no telefone"
    assert events[0].actor_display_name == "Renan"


def test_get_case_events_empty_history() -> None:
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[[]])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    assert repository.get_case_events("case-1") == []
