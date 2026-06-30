"""Coverage for Sprint 5: support-team WhatsApp notification fan-out.

Two layers: the pure renderer, and the write-path enqueue against a scripted
fake cursor (mirroring the support-inbox write-path tests).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from app.db.operational import ChatAuditInput, HANDOFF_QUEUED, OperationalRepository
from app.notifications.support_team import render_support_team_notifications


# --------------------------------------------------------------------------- #
# Pure renderer
# --------------------------------------------------------------------------- #


def test_render_one_notification_per_distinct_recipient() -> None:
    notifications = render_support_team_notifications(
        turn_id="turn-1",
        support_case_id="case-1",
        domain="suporte-vps-whatsapp",
        handoff_reasons=["low_confidence", "sensitive_topic"],
        summary="Cliente nao consegue reiniciar a VPS",
        references=["kb:vps-restart", "kb:handoff"],
        recipients=["5511999990001", "5511999990002", " 5511999990001 "],
    )

    # Duplicate (after trim) collapses to one.
    assert [n.to for n in notifications] == ["5511999990001", "5511999990002"]
    text = notifications[0].text
    assert "Caso: case-1" in text
    assert "Dominio: suporte-vps-whatsapp" in text
    assert "Motivo: low_confidence, sensitive_topic" in text
    assert "Resumo: Cliente nao consegue reiniciar a VPS" in text
    assert "Referencias: kb:vps-restart, kb:handoff" in text
    # Stable, recipient-specific, and never the raw phone number.
    assert notifications[0].idempotency_key.startswith("support_notify:turn-1:")
    assert notifications[0].idempotency_key != notifications[1].idempotency_key
    assert "5511999990001" not in notifications[0].idempotency_key


def test_render_returns_empty_without_recipients() -> None:
    assert (
        render_support_team_notifications(
            turn_id="turn-1",
            support_case_id="case-1",
            domain="vendas",
            handoff_reasons=[],
            summary="x",
            references=[],
            recipients=["", "   "],
        )
        == []
    )


def test_render_is_stable_across_retries() -> None:
    kwargs = dict(
        turn_id="turn-9",
        support_case_id="case-9",
        domain="vendas",
        handoff_reasons=["low_confidence"],
        summary="resumo",
        references=[],
        recipients=["5511999990001"],
    )
    first = render_support_team_notifications(**kwargs)
    second = render_support_team_notifications(**kwargs)
    assert first[0].idempotency_key == second[0].idempotency_key


# --------------------------------------------------------------------------- #
# Write-path enqueue (scripted fake cursor)
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

    def __init__(self, cursor: _RecordingCursor, *, settings: SimpleNamespace) -> None:
        self.settings = settings
        self._cursor = cursor

    @contextmanager
    def transaction(self):
        yield SimpleNamespace(cursor=lambda: self._cursor)


def _settings(*, notify: bool, recipients: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        persistence_hash_secret="persistence-secret",
        persistence_hash_version="hmac-sha256-v1",
        enable_support_team_whatsapp_notify=notify,
        support_team_whatsapp_recipient_list=recipients,
    )


def _escalated_cursor() -> _RecordingCursor:
    transcript_rows = [
        (1, "user", "minha vps caiu", None, False, [], [], None, None),
        (2, "assistant", "vou te transferir", 0.2, True, ["low_confidence"], ["kb:b"], None, None),
    ]
    return _RecordingCursor(
        fetchone_rows=[
            ("domain-id",),
            (False,),
            ("audit-id", "turn-id"),
            ("conversation-id",),
            (2,),  # count_conversation_turns
            ("support-case-id",),
            ("pending",),  # handoff.requested RETURNING status
        ],
        fetchall_rows=[transcript_rows],
    )


def _record_escalated(repository: OperationalRepository):
    return repository.record_chat(
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


def _whatsapp_inserts(cursor: _RecordingCursor) -> list[tuple]:
    return [
        call
        for call in cursor.calls
        if "INSERT INTO operational_outbox" in call[0]
        and "whatsapp.message.requested" in call[0]
    ]


def test_handoff_enqueues_one_whatsapp_event_per_recipient() -> None:
    cursor = _escalated_cursor()
    repository = OperationalRepository(
        _RecordingRuntime(
            cursor,
            settings=_settings(
                notify=True,
                recipients=["5511999990001", "5511999990002"],
            ),
        )
    )

    status = _record_escalated(repository)
    assert status.handoff_status == HANDOFF_QUEUED

    inserts = _whatsapp_inserts(cursor)
    assert len(inserts) == 2
    payloads = [json.loads(call[1][2]) for call in inserts]
    # Recipient number survives verbatim (not redacted) so delivery works.
    assert {p["to"] for p in payloads} == {"5511999990001", "5511999990002"}
    assert all(p["support_case_id"] == "support-case-id" for p in payloads)
    assert all("Novo atendimento humano" in p["text"] for p in payloads)
    # Idempotency keys are per turn + recipient.
    keys = [call[1][0] for call in inserts]
    assert all(key.startswith("support_notify:turn-id:") for key in keys)
    assert len(set(keys)) == 2


def test_handoff_does_not_enqueue_when_flag_disabled() -> None:
    cursor = _escalated_cursor()
    repository = OperationalRepository(
        _RecordingRuntime(
            cursor,
            settings=_settings(notify=False, recipients=["5511999990001"]),
        )
    )

    status = _record_escalated(repository)
    assert status.handoff_status == HANDOFF_QUEUED
    assert _whatsapp_inserts(cursor) == []


def test_handoff_does_not_enqueue_without_recipients() -> None:
    cursor = _escalated_cursor()
    repository = OperationalRepository(
        _RecordingRuntime(cursor, settings=_settings(notify=True, recipients=[]))
    )

    status = _record_escalated(repository)
    assert status.handoff_status == HANDOFF_QUEUED
    assert _whatsapp_inserts(cursor) == []
