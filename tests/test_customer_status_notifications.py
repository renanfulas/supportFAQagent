"""Cobertura da Fase 2 da ponte WhatsApp<->console: templates, notificacao
proativa nas transicoes (assumiu/resolvido), opt-out de e-mail e o
compositor respondendo fora da janela via template.

O ``ScriptedCursor`` roteia cada SELECT por substring da SQL (nao por ordem
estrita de fila) -- resiliente a reordenar as queries dentro de
``_maybe_notify_customer`` sem quebrar os testes por acidente.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.notifications.customer_status import (
    render_customer_status_email,
    render_customer_status_whatsapp,
)
from app.support.customer_preferences import email_notifications_opted_in
from app.support.transitions import SupportCaseTransitionService
from app.support.wa_binding import encrypt_wa_id
from app.support.whatsapp_bridge import (
    SupportWhatsAppBridgeService,
    UnknownStaffTemplate,
)


ENC_KEY = "test-enc-key"
NOW = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Renderer puro
# --------------------------------------------------------------------------- #


def test_render_whatsapp_freeform_inside_window() -> None:
    n = render_customer_status_whatsapp(
        case_id="c1", to_status="in_progress", window_open=True
    )
    assert n.kind == "freeform"
    assert "atendente assumiu" in n.text
    assert n.idempotency_key == "notify_customer_wa:c1:in_progress"


def test_render_whatsapp_template_outside_window_with_summary() -> None:
    n = render_customer_status_whatsapp(
        case_id="c1", to_status="closed", window_open=False, summary="vps caiu"
    )
    assert n.kind == "template"
    assert n.template_label == "ticket_resolvido"


def test_render_whatsapp_none_for_unrelated_status() -> None:
    for status in ("open", "waiting_customer", "cancelled", "pending_consent"):
        assert (
            render_customer_status_whatsapp(
                case_id="c1", to_status=status, window_open=True
            )
            is None
        )


def test_render_email_respects_opt_out_and_missing_address() -> None:
    assert (
        render_customer_status_email(
            case_id="c1", to_status="closed", customer_email=None, opted_in=True
        )
        is None
    )
    assert (
        render_customer_status_email(
            case_id="c1", to_status="closed", customer_email="a@b.com", opted_in=False
        )
        is None
    )
    sent = render_customer_status_email(
        case_id="c1",
        to_status="closed",
        customer_email="a@b.com",
        opted_in=True,
        summary="resumo x",
    )
    assert sent is not None
    assert sent.to == "a@b.com"
    assert "resumo x" in sent.body
    assert sent.idempotency_key == "notify_customer_email:c1:closed"


# --------------------------------------------------------------------------- #
# customer_preferences: leitura do opt-out
# --------------------------------------------------------------------------- #


class _PrefsCursor:
    def __init__(self, row) -> None:
        self._row = row

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return self._row


def test_email_notifications_default_opt_in_when_no_row() -> None:
    assert email_notifications_opted_in(_PrefsCursor(None), "cust-1") is True


def test_email_notifications_opted_out_explicit_false() -> None:
    cursor = _PrefsCursor(('{"notify_status_by_email": false}',))
    assert email_notifications_opted_in(cursor, "cust-1") is False


def test_email_notifications_ignores_unrelated_keys() -> None:
    cursor = _PrefsCursor(('{"language": "pt"}',))
    assert email_notifications_opted_in(cursor, "cust-1") is True


# --------------------------------------------------------------------------- #
# Transitions: notificacao proativa (via apply(), cursor roteado por SQL)
# --------------------------------------------------------------------------- #


class ScriptedCursor:
    """Roteia cada SELECT por substring da SQL. UPDATE sempre bem-sucedido
    (rowcount=1) -- estes testes nao exercitam CAS perdido, ja coberto em
    tests/test_support_transitions.py."""

    def __init__(self, *, routes: dict[str, object]) -> None:
        self.routes = routes
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 1
        self.template_and_email_inserts: list[tuple[str, tuple]] = []

    def __enter__(self) -> "ScriptedCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        if "INSERT INTO operational_outbox" in sql:
            self.template_and_email_inserts.append((sql, params))

    def fetchone(self):
        sql, _ = self.executed[-1]
        for substring, row in self.routes.items():
            if substring in sql:
                return row
        raise AssertionError(f"ScriptedCursor: no route for SQL: {sql}")


class FakeRuntime:
    def __init__(self, cursor: ScriptedCursor, *, settings) -> None:
        self._cursor = cursor
        self.settings = settings

    @contextmanager
    def transaction(self):
        yield SimpleNamespace(cursor=lambda: self._cursor)


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        support_wa_enc_key=ENC_KEY,
        support_wa_window_hours=24,
        support_wa_template_language="pt_BR",
        support_wa_template_atendente_assumiu="atendente_assumiu",
        support_wa_template_precisa_info="precisa_info",
        support_wa_template_ticket_resolvido="ticket_resolvido",
        support_wa_template_reengajar="reengajar",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _wa_binding_row(*, last_customer_message_at) -> tuple:
    return (encrypt_wa_id("+5511999999999", key=ENC_KEY), last_customer_message_at)


def test_claim_inside_window_enqueues_freeform_whatsapp_and_email() -> None:
    routes = {
        "SELECT status, assignee_staff_id": ("open", None),
        "SELECT display_name FROM staff_members": ("Renan",),
        "SELECT sc.customer_id": ("cust-1", {"summary": "vps caiu"}, "cliente@example.com"),
        "SELECT wa_id_encrypted": _wa_binding_row(last_customer_message_at=NOW - timedelta(hours=1)),
        "SELECT preferences_json": None,  # sem linha -> opt-in default
    }
    cursor = ScriptedCursor(routes=routes)
    service = SupportCaseTransitionService(FakeRuntime(cursor, settings=_settings()))

    service.apply(case_id="case-1", action="claim", actor_staff_id="staff-1", note=None)

    events = {sql_params[1][0]: sql_params for sql_params in cursor.template_and_email_inserts}
    assert "whatsapp.message.requested" in events
    assert "email.message.requested" in events
    wa_payload = events["whatsapp.message.requested"][1][3]
    assert '"phone_number_kind": "support"' in wa_payload
    assert "atendente" in wa_payload.lower()


def test_close_outside_window_enqueues_template_with_summary() -> None:
    routes = {
        "SELECT status, assignee_staff_id": ("in_progress", "staff-1"),
        "SELECT display_name FROM staff_members": ("Renan",),
        "SELECT sc.customer_id": ("cust-1", {"summary": "vps caiu apos migracao"}, None),
        "SELECT wa_id_encrypted": _wa_binding_row(last_customer_message_at=NOW - timedelta(hours=48)),
    }
    cursor = ScriptedCursor(routes=routes)
    service = SupportCaseTransitionService(FakeRuntime(cursor, settings=_settings()))

    service.apply(case_id="case-1", action="close", actor_staff_id="staff-1", note=None)

    events = {sql_params[1][0]: sql_params for sql_params in cursor.template_and_email_inserts}
    assert "whatsapp.template.requested" in events
    assert "email.message.requested" not in events  # sem customer_email -> nada
    payload = events["whatsapp.template.requested"][1][3]
    assert '"template_name": "ticket_resolvido"' in payload


def test_close_respects_email_opt_out() -> None:
    routes = {
        "SELECT status, assignee_staff_id": ("in_progress", "staff-1"),
        "SELECT display_name FROM staff_members": ("Renan",),
        "SELECT sc.customer_id": ("cust-1", {"summary": "x"}, "cliente@example.com"),
        "SELECT wa_id_encrypted": None,  # sem binding -> so o e-mail entra em jogo
        "SELECT preferences_json": ('{"notify_status_by_email": false}',),
    }
    cursor = ScriptedCursor(routes=routes)
    service = SupportCaseTransitionService(FakeRuntime(cursor, settings=_settings()))

    service.apply(case_id="case-1", action="close", actor_staff_id="staff-1", note=None)

    event_types = [params[0] for _, params in cursor.template_and_email_inserts]
    assert "email.message.requested" not in event_types
    assert "whatsapp.message.requested" not in event_types
    assert "whatsapp.template.requested" not in event_types


def test_resume_to_in_progress_does_not_notify() -> None:
    """resume (waiting_customer -> in_progress) fica em silencio -- o cliente
    ja sabe que ha um atendente; so 'claim' dispara 'atendente_assumiu'."""

    routes = {
        "SELECT status, assignee_staff_id": ("waiting_customer", "staff-1"),
        "SELECT display_name FROM staff_members": ("Renan",),
    }
    cursor = ScriptedCursor(routes=routes)
    service = SupportCaseTransitionService(FakeRuntime(cursor, settings=_settings()))

    service.apply(case_id="case-1", action="resume", actor_staff_id="staff-1", note=None)

    assert cursor.template_and_email_inserts == []
    assert not any("SELECT sc.customer_id" in sql for sql, _ in cursor.executed)


def test_wa_enc_key_unset_skips_whatsapp_lookup_but_keeps_email() -> None:
    routes = {
        "SELECT status, assignee_staff_id": ("open", None),
        "SELECT display_name FROM staff_members": ("Renan",),
        "SELECT sc.customer_id": ("cust-1", {}, "cliente@example.com"),
        "SELECT preferences_json": None,
    }
    cursor = ScriptedCursor(routes=routes)
    service = SupportCaseTransitionService(
        FakeRuntime(cursor, settings=_settings(support_wa_enc_key=None))
    )

    service.apply(case_id="case-1", action="claim", actor_staff_id="staff-1", note=None)

    assert not any("SELECT wa_id_encrypted" in sql for sql, _ in cursor.executed)
    event_types = [params[0] for _, params in cursor.template_and_email_inserts]
    assert event_types == ["email.message.requested"]


# --------------------------------------------------------------------------- #
# Compositor: retry via template fora da janela (send_agent_reply)
# --------------------------------------------------------------------------- #


class _FakeCase:
    def __init__(self, wa_id: str, *, last_customer_message_at) -> None:
        self._binding = SimpleNamespace(
            case_id="case-1", wa_id=wa_id, last_customer_message_at=last_customer_message_at,
            bound_at=NOW, expires_at=NOW + timedelta(days=15),
        )

    def get(self, case_id: str):
        return self._binding

    def is_window_open(self, binding, *, window_hours, now=None) -> bool:
        if binding.last_customer_message_at is None:
            return False
        moment = now or NOW
        return moment - binding.last_customer_message_at < timedelta(hours=window_hours)

    def find_open_case_id_by_wa_id(self, wa_id):
        return None

    def bind(self, **kwargs):
        pass

    def touch_customer_message(self, **kwargs):
        pass


def test_send_agent_reply_outside_window_requires_allowed_template() -> None:
    # The validation raises before any cursor is touched (binding/window are
    # both resolved through the fake `bindings` seam), so no database fake is
    # needed at all here.
    bindings = _FakeCase("+5511999999999", last_customer_message_at=NOW - timedelta(hours=48))
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=None,
        client=SimpleNamespace(send_text=lambda **kw: None),
        bindings=bindings,
    )

    with pytest.raises(UnknownStaffTemplate):
        service.send_agent_reply(
            case_id="case-1", staff_id="staff-1", text="oi", template="atendente_assumiu"
        )
