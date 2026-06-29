"""Coverage for the support inbox read surface.

Three layers: the pure context builder, the read repository against a scripted
fake cursor, and the HTTP contract (auth, gating, shapes) via TestClient.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.support.context import build_case_context
from app.support.repository import SupportCaseRepository


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}


# --------------------------------------------------------------------------- #
# Pure context builder
# --------------------------------------------------------------------------- #


def test_build_case_context_assembles_transcript_and_dedupes_references() -> None:
    case = {
        "id": "case-1",
        "domain": "suporte-vps-whatsapp",
        "status": "open",
        "priority": "normal",
        "channel": "whatsapp",
        "request_id": "req-1",
        "reason_codes": ["low_confidence", "sensitive_topic"],
        "context_snapshot": {
            "summary": "Cliente nao consegue reiniciar a VPS",
            "references": ["kb:vps-restart"],
        },
        "opened_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
    }
    transcript = [
        {
            "sequence": 1,
            "role": "user",
            "content": "Minha VPS nao reinicia",
            "confidence": None,
            "escalated": False,
            "handoff_reasons": [],
            "references": [],
            "error_code": None,
            "created_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        },
        {
            "sequence": 2,
            "role": "assistant",
            "content": "Vou te transferir para um humano",
            "confidence": 0.21,
            "escalated": True,
            "handoff_reasons": ["low_confidence"],
            "references": ["kb:vps-restart", "kb:handoff"],
            "error_code": None,
            "created_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        },
    ]

    context = build_case_context(case, transcript)

    assert context.case_id == "case-1"
    assert context.summary == "Cliente nao consegue reiniciar a VPS"
    assert context.turn_count == 2
    assert [turn.role for turn in context.transcript] == ["user", "assistant"]
    # snapshot reference first, then the new one from the turn, no duplicates.
    assert context.references == ["kb:vps-restart", "kb:handoff"]


def test_build_case_context_handles_missing_conversation() -> None:
    case = {
        "id": "case-2",
        "domain": "suporte-vps-whatsapp",
        "status": "open",
        "priority": "high",
        "channel": "api",
        "request_id": "req-2",
        "reason_codes": [],
        "context_snapshot": {},
        "opened_at": None,
        "updated_at": None,
    }

    context = build_case_context(case, [])

    assert context.turn_count == 0
    assert context.transcript == []
    assert context.summary is None
    assert context.references == []


# --------------------------------------------------------------------------- #
# Repository against a scripted fake cursor
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


def test_list_cases_maps_rows_and_summary() -> None:
    rows = [
        (
            "case-1",
            "suporte-vps-whatsapp",
            "open",
            "normal",
            "whatsapp",
            "req-1",
            ["low_confidence"],
            {"summary": "resumo"},
            datetime(2026, 6, 28, tzinfo=timezone.utc),
            datetime(2026, 6, 28, tzinfo=timezone.utc),
        )
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    cases = repository.list_cases(domain=None, status="open", limit=25, offset=0)

    assert len(cases) == 1
    assert cases[0].case_id == "case-1"
    assert cases[0].summary == "resumo"
    assert cases[0].reason_codes == ["low_confidence"]


def test_get_case_with_context_follows_conversation() -> None:
    case_row = (
        "case-1",
        "suporte-vps-whatsapp",
        "open",
        "normal",
        "whatsapp",
        "req-1",
        ["low_confidence"],
        {"summary": "resumo", "references": ["kb:a"]},
        "conv-1",
        datetime(2026, 6, 28, tzinfo=timezone.utc),
        datetime(2026, 6, 28, tzinfo=timezone.utc),
    )
    transcript_rows = [
        (1, "user", "oi", None, False, [], [], None, datetime(2026, 6, 28, tzinfo=timezone.utc)),
        (2, "assistant", "transferindo", 0.2, True, ["low_confidence"], ["kb:b"], None, datetime(2026, 6, 28, tzinfo=timezone.utc)),
    ]
    cursor = FakeCursor(
        fetchone_results=[case_row],
        fetchall_results=[transcript_rows],
    )
    repository = SupportCaseRepository(FakeRuntime(cursor))

    context = repository.get_case_with_context("case-1")

    assert context is not None
    assert context.turn_count == 2
    assert context.references == ["kb:a", "kb:b"]


def test_get_case_with_context_returns_none_when_absent() -> None:
    cursor = FakeCursor(fetchone_results=[None], fetchall_results=[])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    assert repository.get_case_with_context("missing") is None


def test_get_case_with_context_skips_transcript_without_conversation() -> None:
    case_row = (
        "case-1",
        "suporte-vps-whatsapp",
        "open",
        "normal",
        "api",
        "req-1",
        [],
        {},
        None,  # conversation_id
        None,
        None,
    )
    cursor = FakeCursor(fetchone_results=[case_row], fetchall_results=[])
    repository = SupportCaseRepository(FakeRuntime(cursor))

    context = repository.get_case_with_context("case-1")

    assert context is not None
    assert context.turn_count == 0
    # No transcript query should have run (only the case SELECT).
    assert len(cursor.executed) == 1


# --------------------------------------------------------------------------- #
# HTTP contract
# --------------------------------------------------------------------------- #


@contextmanager
def _client_with_runtime(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, runtime):
    from app.main import create_app

    monkeypatch.setenv("ENABLE_SUPPORT_INBOX", "true" if enabled else "false")
    get_settings.cache_clear()
    try:
        app = create_app()
        if runtime is not None:
            app.state.database_runtime = runtime
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def test_list_endpoint_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client_with_runtime(monkeypatch, enabled=True, runtime=None) as client:
        response = client.get("/internal/support-cases")
    assert response.status_code == 403


def test_endpoint_is_dark_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client_with_runtime(monkeypatch, enabled=False, runtime=None) as client:
        response = client.get("/internal/support-cases", headers=API_KEY_HEADER)
    assert response.status_code == 404


def test_list_endpoint_returns_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        (
            "case-1",
            "suporte-vps-whatsapp",
            "open",
            "normal",
            "whatsapp",
            "req-1",
            ["low_confidence"],
            {"summary": "resumo"},
            datetime(2026, 6, 28, tzinfo=timezone.utc),
            datetime(2026, 6, 28, tzinfo=timezone.utc),
        )
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows])
    with _client_with_runtime(
        monkeypatch, enabled=True, runtime=FakeRuntime(cursor)
    ) as client:
        response = client.get(
            "/internal/support-cases?status=open", headers=API_KEY_HEADER
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["cases"][0]["case_id"] == "case-1"
    assert body["cases"][0]["summary"] == "resumo"


def test_list_endpoint_rejects_unknown_status(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client_with_runtime(monkeypatch, enabled=True, runtime=None) as client:
        response = client.get(
            "/internal/support-cases?status=banana", headers=API_KEY_HEADER
        )
    assert response.status_code == 422


def test_detail_endpoint_assembles_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    case_row = (
        "case-1",
        "suporte-vps-whatsapp",
        "open",
        "normal",
        "whatsapp",
        "req-1",
        ["low_confidence"],
        {"summary": "resumo", "references": ["kb:a"]},
        "conv-1",
        datetime(2026, 6, 28, tzinfo=timezone.utc),
        datetime(2026, 6, 28, tzinfo=timezone.utc),
    )
    transcript_rows = [
        (1, "user", "oi", None, False, [], [], None, datetime(2026, 6, 28, tzinfo=timezone.utc)),
        (2, "assistant", "transferindo", 0.2, True, ["low_confidence"], ["kb:b"], None, datetime(2026, 6, 28, tzinfo=timezone.utc)),
    ]
    cursor = FakeCursor(
        fetchone_results=[case_row], fetchall_results=[transcript_rows]
    )
    with _client_with_runtime(
        monkeypatch, enabled=True, runtime=FakeRuntime(cursor)
    ) as client:
        response = client.get(
            "/internal/support-cases/case-1", headers=API_KEY_HEADER
        )

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "case-1"
    assert body["turn_count"] == 2
    assert body["references"] == ["kb:a", "kb:b"]
    assert [turn["role"] for turn in body["transcript"]] == ["user", "assistant"]


def test_detail_endpoint_returns_404_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(fetchone_results=[None], fetchall_results=[])
    with _client_with_runtime(
        monkeypatch, enabled=True, runtime=FakeRuntime(cursor)
    ) as client:
        response = client.get(
            "/internal/support-cases/missing", headers=API_KEY_HEADER
        )
    assert response.status_code == 404
