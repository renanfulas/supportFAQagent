"""Coverage for the Fase C console metrics: pure builders, aggregated SQL
(scripted fake cursor) and the HTTP contract.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.support.metrics import (
    SAMPLE_SIZE_WARNING_THRESHOLD,
    SupportMetricsRepository,
    build_backlog_metrics,
    build_console_metrics,
    build_feedback_block,
    build_throughput_series,
    resolve_window,
)
from app.support.repository import ActiveCaseSet, SupportCaseSummary
from app.support.staff_auth import StaffMember
from app.web_auth.service import _hmac_digest


IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
STAFF_PHONE = "+5511999990001"


SETTINGS = SimpleNamespace(
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
    support_console_timezone="America/Sao_Paulo",
    support_console_active_cases_cap=500,
)


# --------------------------------------------------------------------------- #
# resolve_window: corte no fuso do time, nao em UTC
# --------------------------------------------------------------------------- #


def test_resolve_window_14d_uses_local_calendar_days() -> None:
    # 2026-07-03T02:00 UTC = 2026-07-02T23:00 em Sao Paulo (UTC-3): o dia
    # local ainda e 07-02, nao 07-03 -- um corte em UTC erraria por um dia.
    now = datetime(2026, 7, 3, 2, 0, tzinfo=UTC)

    window = resolve_window("14d", now=now, timezone_name="America/Sao_Paulo")

    assert window.end_date_local == date(2026, 7, 2)
    assert window.start_date_local == date(2026, 6, 19)  # 14 dias corridos
    assert window.start_utc == datetime(2026, 6, 19, 3, 0, tzinfo=UTC)
    assert window.end_utc == now


def test_resolve_window_30d() -> None:
    now = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)

    window = resolve_window("30d", now=now, timezone_name="America/Sao_Paulo")

    assert (window.end_date_local - window.start_date_local).days == 29


def test_resolve_window_rejects_unknown_window() -> None:
    with pytest.raises(ValueError):
        resolve_window("7d", now=datetime.now(UTC), timezone_name="America/Sao_Paulo")


# --------------------------------------------------------------------------- #
# build_backlog_metrics: mesmo caminho Python da fila
# --------------------------------------------------------------------------- #


class _FakeCaseRepository:
    def __init__(self, active: ActiveCaseSet) -> None:
        self._active = active
        self.calls: list[dict] = []

    def list_active_cases(self, **kwargs):
        self.calls.append(kwargs)
        return self._active


def _summary(
    case_id: str,
    *,
    status: str = "open",
    priority: str = "normal",
    opened_at: datetime,
    waiting_seconds: float = 0.0,
) -> SupportCaseSummary:
    return SupportCaseSummary(
        case_id=case_id,
        domain="suporte-vps-whatsapp",
        status=status,
        priority=priority,
        channel="whatsapp",
        request_id=f"req-{case_id}",
        reason_codes=[],
        summary=None,
        turn_count=None,
        opened_at=opened_at,
        updated_at=opened_at,
        waiting_seconds=waiting_seconds,
    )


def test_build_backlog_metrics_buckets_by_color_and_status() -> None:
    now = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    active = ActiveCaseSet(
        cases=[
            _summary("green", opened_at=now - timedelta(minutes=10)),
            _summary(
                "red", priority="urgent", opened_at=now - timedelta(hours=6), status="in_progress"
            ),
            _summary(
                "paused",
                priority="urgent",
                opened_at=now - timedelta(hours=6),
                status="waiting_customer",
            ),
        ],
        db_now=now,
        truncated=False,
    )
    repository = _FakeCaseRepository(active)

    backlog = build_backlog_metrics(repository, domain=None, cap=500, settings=SETTINGS)

    assert backlog["by_color"] == {"green": 1, "yellow": 0, "red": 1, "paused": 1}
    assert backlog["by_status"] == {"open": 1, "in_progress": 1, "waiting_customer": 1}
    assert backlog["truncated"] is False
    assert repository.calls[0]["cap"] == 500


def test_build_backlog_metrics_reports_truncated() -> None:
    now = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    active = ActiveCaseSet(
        cases=[_summary("case-1", opened_at=now)], db_now=now, truncated=True
    )
    repository = _FakeCaseRepository(active)

    backlog = build_backlog_metrics(repository, domain=None, cap=1, settings=SETTINGS)

    assert backlog["truncated"] is True


def test_build_backlog_metrics_empty_active_set() -> None:
    active = ActiveCaseSet(cases=[], db_now=None, truncated=False)
    repository = _FakeCaseRepository(active)

    backlog = build_backlog_metrics(repository, domain=None, cap=500, settings=SETTINGS)

    assert backlog["by_color"] == {"green": 0, "yellow": 0, "red": 0, "paused": 0}
    assert backlog["by_status"] == {}


# --------------------------------------------------------------------------- #
# build_throughput_series: zero-fill
# --------------------------------------------------------------------------- #


def test_build_throughput_series_zero_fills_gaps() -> None:
    counts = {date(2026, 7, 1): {"opened": 3, "closed": 1}}

    series = build_throughput_series(
        counts, start_date_local=date(2026, 6, 30), end_date_local=date(2026, 7, 2)
    )

    assert series == [
        {"day": "2026-06-30", "opened": 0, "closed": 0},
        {"day": "2026-07-01", "opened": 3, "closed": 1},
        {"day": "2026-07-02", "opened": 0, "closed": 0},
    ]


def test_build_throughput_series_single_day_window() -> None:
    series = build_throughput_series(
        {}, start_date_local=date(2026, 7, 1), end_date_local=date(2026, 7, 1)
    )
    assert series == [{"day": "2026-07-01", "opened": 0, "closed": 0}]


# --------------------------------------------------------------------------- #
# build_feedback_block: helpful_rate + amostra pequena
# --------------------------------------------------------------------------- #


def test_build_feedback_block_computes_rate_and_flags_small_sample() -> None:
    raw = {"helpful": 3, "not_helpful": 1, "unknown_domain_count": 2}

    block = build_feedback_block(raw)

    assert block["helpful_rate"] == 0.75
    assert block["unknown_domain_count"] == 2
    assert block["sample_note"] == "amostra pequena"


def test_build_feedback_block_large_sample_has_no_note() -> None:
    raw = {
        "helpful": SAMPLE_SIZE_WARNING_THRESHOLD,
        "not_helpful": SAMPLE_SIZE_WARNING_THRESHOLD,
        "unknown_domain_count": 0,
    }

    block = build_feedback_block(raw)

    assert "sample_note" not in block


def test_build_feedback_block_zero_total_has_no_rate() -> None:
    block = build_feedback_block({"helpful": 0, "not_helpful": 0, "unknown_domain_count": 0})

    assert block["helpful_rate"] is None
    assert block["sample_note"] == "amostra pequena"


# --------------------------------------------------------------------------- #
# SupportMetricsRepository: SQL agregado (fake cursor)
# --------------------------------------------------------------------------- #


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


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    @contextmanager
    def transaction(self):
        yield SimpleNamespace(cursor=lambda: self._cursor)


WINDOW_START = datetime(2026, 6, 19, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 3, tzinfo=UTC)


def test_get_throughput_counts_merges_opened_and_closed() -> None:
    cursor = FakeCursor(
        fetchone_results=[],
        fetchall_results=[
            [(date(2026, 7, 1), 3), (date(2026, 7, 2), 1)],
            [(date(2026, 7, 1), 2)],
        ],
    )
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    counts = repository.get_throughput_counts(
        domain=None,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        timezone_name="America/Sao_Paulo",
    )

    assert counts == {
        date(2026, 7, 1): {"opened": 3, "closed": 2},
        date(2026, 7, 2): {"opened": 1},
    }


def test_get_escalation_reasons_maps_rows() -> None:
    cursor = FakeCursor(
        fetchone_results=[],
        fetchall_results=[[("low_confidence", 12), ("explicit_human_request", 4)]],
    )
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    reasons = repository.get_escalation_reasons(
        domain="vendas", window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert reasons == [
        {"reason_code": "low_confidence", "count": 12},
        {"reason_code": "explicit_human_request", "count": 4},
    ]
    _, params = cursor.executed[0]
    assert "vendas" in params


def test_get_feedback_metrics_counts_helpful_and_orphan() -> None:
    cursor = FakeCursor(fetchone_results=[(34, 6, 3)], fetchall_results=[])
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    result = repository.get_feedback_metrics(
        domain=None, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert result == {"helpful": 34, "not_helpful": 6, "unknown_domain_count": 3}


def test_get_feedback_metrics_handles_null_aggregates() -> None:
    cursor = FakeCursor(fetchone_results=[(None, None, None)], fetchall_results=[])
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    result = repository.get_feedback_metrics(
        domain=None, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert result == {"helpful": 0, "not_helpful": 0, "unknown_domain_count": 0}


def test_get_response_times_maps_medians() -> None:
    cursor = FakeCursor(fetchone_results=[(1800.0,), (5400.0,)], fetchall_results=[])
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    result = repository.get_response_times(
        domain=None, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert result == {
        "median_seconds_to_first_action": 1800.0,
        "median_seconds_to_close": 5400.0,
    }


def test_get_response_times_null_when_no_data() -> None:
    cursor = FakeCursor(fetchone_results=[(None,), (None,)], fetchall_results=[])
    repository = SupportMetricsRepository(FakeRuntime(cursor))

    result = repository.get_response_times(
        domain=None, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert result == {
        "median_seconds_to_first_action": None,
        "median_seconds_to_close": None,
    }


# --------------------------------------------------------------------------- #
# build_console_metrics: orquestracao ponta a ponta (fixtures deterministicas)
# --------------------------------------------------------------------------- #


def test_build_console_metrics_end_to_end() -> None:
    now = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    active = ActiveCaseSet(
        cases=[_summary("case-1", opened_at=now - timedelta(minutes=5))],
        db_now=now,
        truncated=False,
    )
    case_repository = _FakeCaseRepository(active)
    metrics_cursor = FakeCursor(
        fetchone_results=[(10, 2, 1), (900.0,), (None,)],
        fetchall_results=[
            [(date(2026, 7, 2), 4)],
            [(date(2026, 7, 2), 3)],
            [("low_confidence", 5)],
        ],
    )
    metrics_repository = SupportMetricsRepository(FakeRuntime(metrics_cursor))

    metrics = build_console_metrics(
        case_repository=case_repository,
        metrics_repository=metrics_repository,
        window="14d",
        domain=None,
        settings=SETTINGS,
        now=now,
    )

    assert metrics["backlog"]["by_color"]["green"] == 1
    assert len(metrics["throughput"]) == 14
    assert metrics["throughput"][-2] == {"day": "2026-07-02", "opened": 4, "closed": 3}
    assert metrics["escalation_reasons"] == [{"reason_code": "low_confidence", "count": 5}]
    assert metrics["feedback"]["helpful"] == 10
    assert metrics["feedback"]["unknown_domain_count"] == 1
    assert metrics["response_times"]["median_seconds_to_first_action"] == 900.0
    assert metrics["response_times"]["median_seconds_to_close"] is None


def test_build_console_metrics_rejects_unknown_window() -> None:
    with pytest.raises(ValueError):
        build_console_metrics(
            case_repository=_FakeCaseRepository(
                ActiveCaseSet(cases=[], db_now=None, truncated=False)
            ),
            metrics_repository=SupportMetricsRepository(FakeRuntime(FakeCursor([], []))),
            window="7d",
            domain=None,
            settings=SETTINGS,
            now=datetime.now(UTC),
        )


# --------------------------------------------------------------------------- #
# Contrato HTTP
# --------------------------------------------------------------------------- #


@contextmanager
def _console_client(monkeypatch: pytest.MonkeyPatch):
    from app.main import create_app

    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", IDENTITY_SECRET)
    monkeypatch.setenv("OTP_DIGEST_SECRET", OTP_SECRET)
    monkeypatch.setenv("SUPPORT_CONSOLE_TIMEZONE", "America/Sao_Paulo")
    get_settings.cache_clear()
    try:
        app = create_app()
        yield TestClient(app), app
    finally:
        get_settings.cache_clear()


def _seed_staff(app) -> None:
    app.state.support_console_runtime.service.staff_store.add_staff(
        StaffMember(
            id=str(uuid4()),
            phone_hash=_hmac_digest(IDENTITY_SECRET, STAFF_PHONE),
            phone_last4=STAFF_PHONE[-4:],
            display_name="Renan",
        )
    )


def _login(client: TestClient, app) -> None:
    start = client.post("/web/support/auth/start", json={"phone": STAFF_PHONE})
    code = app.state.support_console_runtime.delivery.requests[-1].code
    confirm = client.post(
        "/web/support/auth/confirm",
        json={
            "challenge_id": start.json()["challenge_id"],
            "code": code,
            "phone": STAFF_PHONE,
        },
    )
    assert confirm.status_code == 200


def test_metrics_endpoint_is_404_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "false")
    from app.main import create_app

    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.get("/web/support/metrics")
    finally:
        get_settings.cache_clear()
    assert response.status_code == 404


def test_metrics_endpoint_requires_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        response = client.get("/web/support/metrics")
    assert response.status_code == 401


def test_metrics_endpoint_rejects_unknown_window(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        response = client.get("/web/support/metrics?window=7d")
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_window"


def test_metrics_endpoint_returns_full_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)

        class _NowThenMetricsCursor(FakeCursor):
            def __init__(self) -> None:
                super().__init__(
                    fetchone_results=[
                        (datetime(2026, 7, 3, 18, 0, tzinfo=UTC),),  # database_now()
                        (5, 1, 2),  # feedback
                        (600.0,),  # median first action
                        (1200.0,),  # median to close
                    ],
                    fetchall_results=[
                        [],  # active cases (list_active_cases)
                        [],  # throughput opened
                        [],  # throughput closed
                        [],  # escalation reasons
                    ],
                )

        app.state.database_runtime = FakeRuntime(_NowThenMetricsCursor())

        response = client.get("/web/support/metrics?window=14d")

    assert response.status_code == 200
    body = response.json()
    assert body["window"] == "14d"
    assert body["domain"] is None
    assert body["backlog"] == {
        "by_color": {"green": 0, "yellow": 0, "red": 0, "paused": 0},
        "by_status": {},
        "truncated": False,
    }
    assert len(body["throughput"]) == 14
    assert body["escalation_reasons"] == []
    assert body["feedback"] == {
        "helpful": 5,
        "not_helpful": 1,
        "helpful_rate": round(5 / 6, 4),
        "unknown_domain_count": 2,
        "sample_note": "amostra pequena",
    }
    assert body["response_times"] == {
        "median_seconds_to_first_action": 600.0,
        "median_seconds_to_close": 1200.0,
    }


def test_metrics_endpoint_logs_never_leak_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(
                fetchone_results=[
                    (datetime(2026, 7, 3, 18, 0, tzinfo=UTC),),
                    (0, 0, 0),
                    (None,),
                    (None,),
                ],
                fetchall_results=[[], [], [], []],
            )
        )
        with caplog.at_level(logging.INFO):
            response = client.get("/web/support/metrics")

    assert response.status_code == 200
    assert "support_console_metrics_viewed" in caplog.text
    assert STAFF_PHONE not in caplog.text
