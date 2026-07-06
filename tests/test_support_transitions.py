"""Unit coverage for the Fase B transition service (scripted fake cursor).

Mirrors the compare-and-swap pattern already used by the consent gate: a
``SELECT ... FOR UPDATE`` reads the current state, the ``UPDATE`` carries the
current status as an extra guard, and the audit event is inserted in the same
transaction. The fake cursor lets us script the ``UPDATE`` rowcount to
simulate a lost CAS without a real database.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.support.transitions import (
    CaseNotFound,
    InvalidTransition,
    SupportCaseTransitionService,
)

# Fase 2: claim/close agora tambem consultam support_cases/customers para a
# notificacao proativa (_maybe_notify_customer). support_wa_enc_key=None faz
# _resolve_wa_window() retornar sem tocar case_whatsapp_bindings; um
# customer_id None no SELECT pula o bloco de e-mail -- so precisa de UM
# fetchone extra por transicao notificavel (claim->in_progress ou close).
NO_NOTIFICATION_SETTINGS = SimpleNamespace(support_wa_enc_key=None)
NO_CUSTOMER_ROW = (None, None, None)


class FakeCursor:
    def __init__(self, *, fetchone_results: list, update_rowcounts: list[int] | None = None) -> None:
        self._fetchone = list(fetchone_results)
        self._update_rowcounts = list(update_rowcounts) if update_rowcounts is not None else [1]
        self.rowcount = 0
        self.executed: list[tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        if "UPDATE support_cases" in sql:
            self.rowcount = self._update_rowcounts.pop(0)

    def fetchone(self):
        return self._fetchone.pop(0)


class FakeRuntime:
    def __init__(self, cursor: FakeCursor, *, settings=NO_NOTIFICATION_SETTINGS) -> None:
        self._cursor = cursor
        self.settings = settings

    @contextmanager
    def transaction(self):
        yield _Connection(self._cursor)


class _Connection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


ACTOR_ID = "staff-actor"


def _service(cursor: FakeCursor) -> SupportCaseTransitionService:
    return SupportCaseTransitionService(FakeRuntime(cursor))


# --------------------------------------------------------------------------- #
# Matriz de transicoes validas
# --------------------------------------------------------------------------- #


def test_claim_open_case_sets_assignee_and_in_progress() -> None:
    cursor = FakeCursor(fetchone_results=[("open", None), ("Renan",), NO_CUSTOMER_ROW])
    service = _service(cursor)

    result = service.apply(case_id="case-1", action="claim", actor_staff_id=ACTOR_ID, note=None)

    assert result.from_status == "open"
    assert result.to_status == "in_progress"
    assert result.assignee_staff_id == ACTOR_ID
    assert result.assignee_display_name == "Renan"
    update_sql, update_params = cursor.executed[1]
    assert "assignee_staff_id IS NULL" in update_sql
    assert update_params == ("in_progress", ACTOR_ID, "case-1")
    insert_sql, insert_params = cursor.executed[2]
    assert "INSERT INTO support_case_events" in insert_sql
    assert insert_params == ("case-1", ACTOR_ID, "claim", "open", "in_progress", None)


def test_release_clears_assignee_and_reopens() -> None:
    cursor = FakeCursor(fetchone_results=[("in_progress", "someone-else")])
    service = _service(cursor)

    result = service.apply(
        case_id="case-1", action="release", actor_staff_id=ACTOR_ID, note=None
    )

    assert result.to_status == "open"
    assert result.assignee_staff_id is None
    assert result.assignee_display_name is None
    # Sem novo assignee, nao ha lookup de display_name.
    assert all("SELECT display_name" not in sql for sql, _ in cursor.executed)


def test_wait_customer_and_resume_round_trip() -> None:
    # to_status='waiting_customer' nao e notificavel -- sem fetchone extra.
    cursor = FakeCursor(fetchone_results=[("in_progress", "staff-1"), ("Renan",)])
    service = _service(cursor)

    result = service.apply(
        case_id="case-1", action="wait_customer", actor_staff_id=ACTOR_ID, note=None
    )

    assert result.to_status == "waiting_customer"
    # wait_customer/resume nao mexem no dono do caso.
    assert result.assignee_staff_id == "staff-1"


def test_close_sets_closed_at() -> None:
    cursor = FakeCursor(fetchone_results=[("in_progress", "staff-1"), ("Renan",), NO_CUSTOMER_ROW])
    service = _service(cursor)

    result = service.apply(
        case_id="case-1", action="close", actor_staff_id=ACTOR_ID, note=None
    )

    assert result.to_status == "closed"
    update_sql, _ = cursor.executed[1]
    assert "closed_at = now()" in update_sql


@pytest.mark.parametrize("from_status", ["open", "in_progress"])
def test_cancel_sets_closed_at_from_open_or_in_progress(from_status: str) -> None:
    cursor = FakeCursor(fetchone_results=[(from_status, None)])
    service = _service(cursor)

    result = service.apply(
        case_id="case-1", action="cancel", actor_staff_id=ACTOR_ID, note=None
    )

    assert result.to_status == "cancelled"
    update_sql, _ = cursor.executed[1]
    assert "closed_at = now()" in update_sql


def test_cancel_from_pending_consent_closes_abandoned_ticket() -> None:
    # Valvula de escape: o ticket que nasceu 'pending_consent' e cujo cliente
    # nunca confirmou o consentimento pode ser encerrado pelo time.
    cursor = FakeCursor(fetchone_results=[("pending_consent", None)])
    service = _service(cursor)

    result = service.apply(
        case_id="case-1", action="cancel", actor_staff_id=ACTOR_ID, note=None
    )

    assert result.from_status == "pending_consent"
    assert result.to_status == "cancelled"
    update_sql, update_params = cursor.executed[1]
    assert "closed_at = now()" in update_sql
    assert "pending_consent" in update_params
    insert_sql, insert_params = cursor.executed[2]
    assert "INSERT INTO support_case_events" in insert_sql
    assert insert_params[3:5] == ("pending_consent", "cancelled")


def test_pending_consent_only_allows_cancel() -> None:
    # Nenhuma outra acao sai de pending_consent (claim/close/etc).
    for action in ("claim", "close", "wait_customer", "resume", "release"):
        cursor = FakeCursor(fetchone_results=[("pending_consent", None)])
        service = _service(cursor)
        with pytest.raises(InvalidTransition) as exc_info:
            service.apply(
                case_id="case-1", action=action, actor_staff_id=ACTOR_ID, note=None
            )
        assert exc_info.value.status == "pending_consent"


# --------------------------------------------------------------------------- #
# Transicoes invalidas
# --------------------------------------------------------------------------- #


def test_claim_already_assigned_is_rejected() -> None:
    cursor = FakeCursor(fetchone_results=[("open", "someone-else")])
    service = _service(cursor)

    with pytest.raises(InvalidTransition) as exc_info:
        service.apply(case_id="case-1", action="claim", actor_staff_id=ACTOR_ID, note=None)

    assert exc_info.value.status == "open"
    # Nenhum UPDATE/INSERT foi executado -- so a leitura FOR UPDATE.
    assert len(cursor.executed) == 1


def test_action_not_valid_from_current_status_is_rejected() -> None:
    cursor = FakeCursor(fetchone_results=[("open", None)])
    service = _service(cursor)

    with pytest.raises(InvalidTransition) as exc_info:
        service.apply(case_id="case-1", action="resume", actor_staff_id=ACTOR_ID, note=None)

    assert exc_info.value.status == "open"
    assert len(cursor.executed) == 1


def test_case_not_found_raises() -> None:
    cursor = FakeCursor(fetchone_results=[None])
    service = _service(cursor)

    with pytest.raises(CaseNotFound):
        service.apply(case_id="missing", action="claim", actor_staff_id=ACTOR_ID, note=None)


def test_unknown_action_raises_value_error() -> None:
    cursor = FakeCursor(fetchone_results=[])
    service = _service(cursor)

    with pytest.raises(ValueError):
        service.apply(case_id="case-1", action="teleport", actor_staff_id=ACTOR_ID, note=None)
    # Nem chegou a consultar o banco.
    assert cursor.executed == []


# --------------------------------------------------------------------------- #
# CAS perdido (defesa em profundidade) -- nenhum evento gravado
# --------------------------------------------------------------------------- #


def test_lost_cas_raises_invalid_transition_without_recording_event() -> None:
    cursor = FakeCursor(fetchone_results=[("open", None)], update_rowcounts=[0])
    service = _service(cursor)

    with pytest.raises(InvalidTransition) as exc_info:
        service.apply(case_id="case-1", action="claim", actor_staff_id=ACTOR_ID, note=None)

    assert exc_info.value.status == "open"
    assert all("INSERT INTO support_case_events" not in sql for sql, _ in cursor.executed)


# --------------------------------------------------------------------------- #
# Nota: sanitizada, truncada, vazia vira None
# --------------------------------------------------------------------------- #


def test_note_is_sanitized_before_persisting() -> None:
    cursor = FakeCursor(fetchone_results=[("in_progress", "staff-1"), ("Renan",), NO_CUSTOMER_ROW])
    service = _service(cursor)

    service.apply(
        case_id="case-1",
        action="close",
        actor_staff_id=ACTOR_ID,
        note="cartao do cliente 4111 1111 1111 1111 confirmado",
    )

    insert_sql, insert_params = next(
        call for call in cursor.executed if "INSERT INTO support_case_events" in call[0]
    )
    persisted_note = insert_params[-1]
    assert "4111 1111 1111 1111" not in persisted_note


def test_blank_note_becomes_none() -> None:
    cursor = FakeCursor(fetchone_results=[("in_progress", "staff-1"), ("Renan",), NO_CUSTOMER_ROW])
    service = _service(cursor)

    result_call = service.apply(
        case_id="case-1", action="close", actor_staff_id=ACTOR_ID, note="   "
    )

    insert_sql, insert_params = next(
        call for call in cursor.executed if "INSERT INTO support_case_events" in call[0]
    )
    assert insert_params[-1] is None
    assert result_call.to_status == "closed"


def test_note_is_truncated_to_max_length() -> None:
    cursor = FakeCursor(fetchone_results=[("in_progress", "staff-1"), ("Renan",), NO_CUSTOMER_ROW])
    service = _service(cursor)

    service.apply(
        case_id="case-1", action="close", actor_staff_id=ACTOR_ID, note="x" * 900
    )

    insert_sql, insert_params = next(
        call for call in cursor.executed if "INSERT INTO support_case_events" in call[0]
    )
    assert len(insert_params[-1]) <= 500
