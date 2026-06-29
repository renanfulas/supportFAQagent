"""Coverage for the support inbox read surface.

Three layers: the pure context builder, the read repository against a scripted
fake cursor, and the HTTP contract (auth, gating, shapes) via TestClient.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.operational import ChatAuditInput, HANDOFF_QUEUED, OperationalRepository
from app.support.context import build_case_context, build_snapshot_context
from app.support.repository import SupportCaseRepository
from app.support.transcript import (
    build_support_snapshot_context,
    fetch_conversation_transcript,
)


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
# Phase B: bounded snapshot context (push-side reuse of the read seam)
# --------------------------------------------------------------------------- #


def _turn_dict(sequence: int, role: str, content: str, references=None) -> dict:
    return {
        "sequence": sequence,
        "role": role,
        "content": content,
        "confidence": None,
        "escalated": False,
        "handoff_reasons": [],
        "references": references or [],
        "error_code": None,
        "created_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
    }


def test_build_snapshot_context_reports_total_and_caps_content() -> None:
    recent = [
        _turn_dict(1, "user", "x" * 50, references=["kb:a"]),
        _turn_dict(2, "assistant", "y" * 50, references=["kb:a", "kb:b"]),
    ]

    block = build_snapshot_context(recent, total_turn_count=25, content_limit=10)

    assert block["turn_count"] == 25
    assert block["included_turn_count"] == 2
    assert block["references"] == ["kb:a", "kb:b"]
    assert all(len(turn["content"]) <= 10 for turn in block["recent_turns"])
    assert [turn["role"] for turn in block["recent_turns"]] == ["user", "assistant"]


def test_build_support_snapshot_context_without_conversation() -> None:
    block = build_support_snapshot_context(cursor=None, conversation_id=None)

    assert block["turn_count"] == 0
    assert block["recent_turns"] == []


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


def test_fetch_conversation_transcript_returns_rows_with_limit() -> None:
    rows = [
        (1, "user", "oi", None, False, [], [], None, None),
        (2, "assistant", "ola", 0.9, False, [], [], None, None),
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows])

    turns = fetch_conversation_transcript(cursor, "conv-1", limit=5)

    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    # The bound is passed through to SQL as the LIMIT parameter.
    _, params = cursor.executed[0]
    assert params[-1] == 5


def test_build_support_snapshot_context_with_cursor() -> None:
    recent_rows = [
        (1, "user", "oi", None, False, [], ["kb:a"], None, None),
        (2, "assistant", "transferindo", 0.2, True, ["low_confidence"], ["kb:b"], None, None),
    ]
    cursor = FakeCursor(fetchone_results=[(7,)], fetchall_results=[recent_rows])

    block = build_support_snapshot_context(cursor, "conv-1")

    assert block["turn_count"] == 7
    assert block["included_turn_count"] == 2
    assert block["references"] == ["kb:a", "kb:b"]


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
# Phase B write-path: organized_context reaches the persisted snapshot
# --------------------------------------------------------------------------- #


class _RecordingCursor:
    def __init__(self, fetchone_rows: list, fetchall_rows: list) -> None:
        self._fetchone = list(fetchone_rows)
        self._fetchall = list(fetchall_rows)
        self.calls: list[tuple] = []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *_) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []


class _RecordingRuntime:
    enabled = True
    persistence_enabled = True

    def __init__(self, cursor: _RecordingCursor) -> None:
        self.settings = SimpleNamespace(
            persistence_hash_secret="persistence-secret",
            persistence_hash_version="hmac-sha256-v1",
        )
        self._cursor = cursor

    @contextmanager
    def transaction(self):
        yield SimpleNamespace(cursor=lambda: self._cursor)


def test_escalated_chat_persists_organized_context_in_snapshot() -> None:
    transcript_rows = [
        (1, "user", "minha vps caiu", None, False, [], [], None, None),
        (2, "assistant", "vou te transferir", 0.2, True, ["low_confidence"], ["kb:b"], None, None),
    ]
    cursor = _RecordingCursor(
        fetchone_rows=[
            ("domain-id",),
            (False,),
            ("audit-id", "turn-id"),
            ("conversation-id",),
            (2,),  # count_conversation_turns
            ("support-case-id",),
            ("pending",),
        ],
        fetchall_rows=[transcript_rows],
    )
    repository = OperationalRepository(_RecordingRuntime(cursor))

    status = repository.record_chat(
        ChatAuditInput(
            request_id="req-1",
            domain="suporte-vps-whatsapp",
            session_id="raw-session",
            question="minha vps caiu",
            answer="vou te transferir",
            confidence=0.2,
            escalated=True,
            handoff_reasons=["low_confidence"],
            references=["kb:b"],
            error_code=None,
        )
    )

    assert status.handoff_status == HANDOFF_QUEUED
    insert = next(
        call for call in cursor.calls if "INSERT INTO support_cases" in call[0]
    )
    snapshot = json.loads(insert[1][6])
    organized = snapshot["organized_context"]
    assert organized["turn_count"] == 2
    assert organized["included_turn_count"] == 2
    assert [turn["role"] for turn in organized["recent_turns"]] == [
        "user",
        "assistant",
    ]
    # The push (outbox) payload carries the same bounded context block.
    outbox = next(
        call for call in cursor.calls if "INSERT INTO operational_outbox" in call[0]
    )
    outbox_payload = json.loads(outbox[1][2])
    assert outbox_payload["organized_context"]["turn_count"] == 2


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


def test_list_endpoint_surfaces_turn_count_from_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (
            "case-1",
            "suporte-vps-whatsapp",
            "open",
            "normal",
            "whatsapp",
            "req-1",
            [],
            {"summary": "resumo", "organized_context": {"turn_count": 9}},
            datetime(2026, 6, 28, tzinfo=timezone.utc),
            datetime(2026, 6, 28, tzinfo=timezone.utc),
        )
    ]
    cursor = FakeCursor(fetchone_results=[], fetchall_results=[rows])
    with _client_with_runtime(
        monkeypatch, enabled=True, runtime=FakeRuntime(cursor)
    ) as client:
        response = client.get("/internal/support-cases", headers=API_KEY_HEADER)

    assert response.status_code == 200
    assert response.json()["cases"][0]["turn_count"] == 9


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
