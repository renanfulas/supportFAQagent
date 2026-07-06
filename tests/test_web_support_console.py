"""HTTP contract for the staff console facade (/web/support/*).

Auth flows run against the in-memory seams created by ``create_app`` (memory
persistence + memory delivery); the case list/detail surface runs against a
scripted fake database runtime, like the internal inbox tests.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.health.service import HealthService
from app.support.staff_auth import StaffMember
from app.web_auth.service import _hmac_digest


IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
STAFF_PHONE = "+5511999990001"
OTHER_PHONE = "+5511999990002"

DB_NOW = datetime(2026, 7, 2, 18, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(
        self,
        fetchone_results: list,
        fetchall_results: list,
        *,
        update_rowcounts: list[int] | None = None,
    ) -> None:
        self._fetchone = list(fetchone_results)
        self._fetchall = list(fetchall_results)
        # Transitions: rowcount defaults to a successful CAS (1) for every
        # UPDATE support_cases unless a test scripts a lost CAS explicitly.
        self._update_rowcounts = list(update_rowcounts) if update_rowcounts is not None else None
        self.rowcount = 0
        self.executed: list[tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        if "UPDATE support_cases" in sql:
            self.rowcount = (
                self._update_rowcounts.pop(0) if self._update_rowcounts is not None else 1
            )

    def fetchone(self):
        return self._fetchone.pop(0)

    def fetchall(self):
        return self._fetchall.pop(0)


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        # Fase 2: claim/close consultam support_cases/customers para a
        # notificacao proativa; enc_key=None faz o lookup de binding WA
        # retornar sem tocar case_whatsapp_bindings.
        self.settings = SimpleNamespace(support_wa_enc_key=None)

    @contextmanager
    def transaction(self):
        yield SimpleNamespace(cursor=lambda: self._cursor)


def _active_row(
    case_id: str,
    *,
    priority: str = "normal",
    status: str = "open",
    opened_at: datetime,
    assignee_staff_id: str | None = None,
    assignee_display_name: str | None = None,
) -> tuple:
    return (
        case_id,
        "suporte-vps-whatsapp",
        status,
        priority,
        "whatsapp",
        f"req-{case_id}",
        ["low_confidence"],
        {"summary": f"resumo {case_id}"},
        opened_at,
        opened_at,
        assignee_staff_id,
        assignee_display_name,
        DB_NOW,
    )


@contextmanager
def _console_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    extra_env: dict[str, str] | None = None,
):
    from app.main import create_app

    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true" if enabled else "false")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", IDENTITY_SECRET)
    monkeypatch.setenv("OTP_DIGEST_SECRET", OTP_SECRET)
    monkeypatch.setenv("SUPPORT_CONSOLE_TIMEZONE", "America/Sao_Paulo")
    for key, value in (extra_env or {}).items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        app = create_app()
        yield TestClient(app), app
    finally:
        get_settings.cache_clear()


def _seed_staff(app, *, display_name: str = "Renan", phone: str = STAFF_PHONE) -> str:
    staff_id = str(uuid4())
    app.state.support_console_runtime.service.staff_store.add_staff(
        StaffMember(
            id=staff_id,
            phone_hash=_hmac_digest(IDENTITY_SECRET, phone),
            phone_last4=phone[-4:],
            display_name=display_name,
        )
    )
    return staff_id


def _login(client: TestClient, app) -> str:
    start = client.post("/web/support/auth/start", json={"phone": STAFF_PHONE})
    assert start.status_code == 202
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
    return confirm.json()["display_name"]


# --------------------------------------------------------------------------- #
# Dark by default
# --------------------------------------------------------------------------- #


def test_whole_surface_is_404_when_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch, enabled=False) as (client, _):
        assert client.post(
            "/web/support/auth/start", json={"phone": STAFF_PHONE}
        ).status_code == 404
        assert client.get("/web/support/auth/session").status_code == 404
        assert client.get("/web/support/cases").status_code == 404


# --------------------------------------------------------------------------- #
# Auth pela API
# --------------------------------------------------------------------------- #


def test_staff_login_flow_and_session_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)

        before = client.get("/web/support/auth/session")
        assert before.status_code == 401
        assert before.json() == {"authenticated": False, "hint": None}

        display_name = _login(client, app)
        assert display_name == "Renan"
        assert "sfa_staff_session" in client.cookies
        assert "sfa_staff_hint" in client.cookies

        session = client.get("/web/support/auth/session")
        assert session.status_code == 200
        body = session.json()
        assert body["authenticated"] is True
        assert body["display_name"] == "Renan"
        assert body["expires_at"]


def test_non_staff_phone_gets_identical_202_and_failing_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)

        response = client.post(
            "/web/support/auth/start", json={"phone": OTHER_PHONE}
        )
        assert response.status_code == 202
        body = response.json()
        assert set(body) == {
            "challenge_id",
            "expires_in_seconds",
            "retry_after_seconds",
        }
        # Nada foi entregue e o confirm cai no mesmo 400 do fluxo normal.
        assert app.state.support_console_runtime.delivery.requests == []
        confirm = client.post(
            "/web/support/auth/confirm",
            json={"challenge_id": body["challenge_id"], "code": "123456"},
        )
        assert confirm.status_code == 400
        assert confirm.json()["detail"] == "invalid_or_expired_code"


def test_start_still_202_when_delivery_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenDelivery:
        def deliver(self, request) -> None:
            from app.web_auth.delivery import OtpDeliveryUnavailable

            raise OtpDeliveryUnavailable

    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        app.state.support_console_runtime.service.delivery = BrokenDelivery()

        response = client.post(
            "/web/support/auth/start", json={"phone": STAFF_PHONE}
        )

        assert response.status_code == 202


def test_start_without_phone_and_without_hint_is_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        response = client.post("/web/support/auth/start", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_phone"


def test_logout_preserves_hint_and_forget_device_removes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Cooldown minimo: este fluxo faz dois starts para o mesmo telefone.
    with _console_client(
        monkeypatch, extra_env={"OTP_RESEND_COOLDOWN_SECONDS": "1"}
    ) as (client, app):
        _seed_staff(app)
        _login(client, app)

        logout = client.post("/web/support/auth/logout", json={})
        assert logout.status_code == 200

        # Sem sessao, mas o lembrete habilita o botao de 1 clique.
        session = client.get("/web/support/auth/session")
        assert session.status_code == 401
        assert session.json()["hint"] == {"display_name": "Renan"}

        # Login de novo so com o lembrete (sem digitar telefone).
        time.sleep(1.1)
        start = client.post("/web/support/auth/start", json={})
        assert start.status_code == 202
        code = app.state.support_console_runtime.delivery.requests[-1].code
        confirm = client.post(
            "/web/support/auth/confirm",
            json={"challenge_id": start.json()["challenge_id"], "code": code},
        )
        assert confirm.status_code == 200

        client.post("/web/support/auth/logout", json={"forget_device": True})
        session = client.get("/web/support/auth/session")
        assert session.status_code == 401
        assert session.json()["hint"] is None


# --------------------------------------------------------------------------- #
# Fila com semaforo
# --------------------------------------------------------------------------- #


def test_cases_require_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, _):
        response = client.get("/web/support/cases")
    assert response.status_code == 401
    assert response.json()["detail"] == "unauthorized"


def test_active_queue_orders_by_attention_and_serves_sla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _active_row("green-fresh", opened_at=DB_NOW - timedelta(minutes=30)),
        _active_row(
            "paused-old",
            priority="urgent",
            status="waiting_customer",
            opened_at=DB_NOW - timedelta(hours=12),
        ),
        _active_row(
            "urgent-overdue",
            priority="urgent",
            opened_at=DB_NOW - timedelta(hours=6),
        ),
    ]
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            # Segundo fetchall: consulta de waiting_seconds (sem eventos).
            FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
        )

        response = client.get("/web/support/cases")

    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "active"
    assert body["truncated"] is False
    assert [case["case_id"] for case in body["cases"]] == [
        "urgent-overdue",
        "paused-old",
        "green-fresh",
    ]
    overdue = body["cases"][0]["sla"]
    assert overdue["color"] == "red"
    assert overdue["paused"] is False
    assert "prazo estourado" in overdue["explanation"]
    paused = body["cases"][1]["sla"]
    assert paused["paused"] is True
    assert paused["color"] != "red"
    assert body["cases"][0]["assignee"] is None


def test_active_queue_color_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _active_row("green-fresh", opened_at=DB_NOW - timedelta(minutes=30)),
        _active_row(
            "urgent-overdue",
            priority="urgent",
            opened_at=DB_NOW - timedelta(hours=6),
        ),
    ]
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
        )

        response = client.get("/web/support/cases?color=green")

    assert response.status_code == 200
    assert [case["case_id"] for case in response.json()["cases"]] == ["green-fresh"]


def test_active_queue_marks_truncated_when_cap_is_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _active_row("case-1", opened_at=DB_NOW - timedelta(hours=2)),
        _active_row("case-2", opened_at=DB_NOW - timedelta(hours=1)),
    ]
    with _console_client(
        monkeypatch, extra_env={"SUPPORT_CONSOLE_ACTIVE_CASES_CAP": "1"}
    ) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            # Segundo fetchall: consulta de waiting_seconds (sem eventos).
            FakeCursor(fetchone_results=[], fetchall_results=[rows, []])
        )

        response = client.get("/web/support/cases")

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert body["count"] == 1


def test_history_view_paginates_without_sla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_row = (
        "closed-1",
        "suporte-vps-whatsapp",
        "closed",
        "normal",
        "whatsapp",
        "req-closed-1",
        [],
        {"summary": "resolvido"},
        DB_NOW - timedelta(days=2),
        DB_NOW - timedelta(days=1),
        None,  # assignee_staff_id
        None,  # assignee_display_name
    )
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(fetchone_results=[], fetchall_results=[[closed_row]])
        )

        response = client.get("/web/support/cases?view=history")

    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "history"
    assert body["cases"][0]["case_id"] == "closed-1"
    assert body["cases"][0]["sla"] is None


def test_invalid_filters_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        assert client.get("/web/support/cases?view=banana").status_code == 422
        assert client.get("/web/support/cases?color=banana").status_code == 422
        assert client.get("/web/support/cases?status=banana").status_code == 422
        assert client.get("/web/support/cases?sort=banana").status_code == 422


def test_case_detail_includes_sla_block(monkeypatch: pytest.MonkeyPatch) -> None:
    case_row = (
        "case-1",
        "suporte-vps-whatsapp",
        "open",
        "urgent",
        "whatsapp",
        "req-1",
        ["low_confidence"],
        {"summary": "resumo", "references": ["kb:a"]},
        "conv-1",
        DB_NOW - timedelta(hours=6),
        DB_NOW - timedelta(hours=6),
        "Ana",
        "ana@example.com",
        "1234",
        None,  # assignee_staff_id
        None,  # assignee_display_name
    )
    transcript_rows = [
        (1, "user", "oi", None, False, [], [], None, DB_NOW - timedelta(hours=6)),
        (
            2,
            "assistant",
            "transferindo",
            0.2,
            True,
            ["low_confidence"],
            ["kb:b"],
            None,
            DB_NOW - timedelta(hours=6),
        ),
    ]
    cursor = FakeCursor(
        fetchone_results=[case_row, (DB_NOW,)],
        # get_case_with_context transcript, get_case_waiting_seconds (no pause
        # events), get_case_events (no history yet).
        fetchall_results=[transcript_rows, [], []],
    )
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(cursor)

        response = client.get("/web/support/cases/case-1")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "case-1"
    assert body["turn_count"] == 2
    assert body["sla"]["color"] == "red"
    assert body["assignee"] is None
    assert body["customer"]["display_label"] == "Ana"


def test_case_detail_404_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(fetchone_results=[None], fetchall_results=[])
        )
        response = client.get("/web/support/cases/missing")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Fase B: transicoes auditadas
# --------------------------------------------------------------------------- #

CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def test_transition_requires_csrf_header(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)

        response = client.post(
            "/web/support/cases/case-1/transition", json={"action": "claim"}
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "csrf_header_required"


def test_transition_requires_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)

        response = client.post(
            "/web/support/cases/case-1/transition",
            json={"action": "claim"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 401


def test_claim_transition_succeeds_and_returns_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app, display_name="Renan")
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(
                fetchone_results=[("open", None), ("Renan",), (None, None, None)],
                fetchall_results=[],
            )
        )

        response = client.post(
            "/web/support/cases/case-1/transition",
            json={"action": "claim", "note": "assumindo o caso"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "case-1"
    assert body["status"] == "in_progress"
    assert body["assignee"] == {"display_name": "Renan"}


def test_release_transition_clears_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(
                fetchone_results=[("in_progress", "someone-else")],
                fetchall_results=[],
            )
        )

        response = client.post(
            "/web/support/cases/case-1/transition",
            json={"action": "release"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "open"
    assert body["assignee"] is None


def test_invalid_transition_returns_409_with_current_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(fetchone_results=[("closed", None)], fetchall_results=[])
        )

        response = client.post(
            "/web/support/cases/case-1/transition",
            json={"action": "claim"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "invalid_transition", "status": "closed"}


def test_transition_case_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(fetchone_results=[None], fetchall_results=[])
        )

        response = client.post(
            "/web/support/cases/missing/transition",
            json={"action": "claim"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "support_case_not_found"


def test_transition_rejects_unknown_action(monkeypatch: pytest.MonkeyPatch) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)

        response = client.post(
            "/web/support/cases/case-1/transition",
            json={"action": "teleport"},
            headers=CSRF_HEADERS,
        )

    assert response.status_code == 422


def test_transition_note_never_leaks_into_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)
        app.state.database_runtime = FakeRuntime(
            FakeCursor(
                fetchone_results=[("open", None), ("Renan",), (None, None, None)],
                fetchall_results=[],
            )
        )

        with caplog.at_level(logging.INFO):
            response = client.post(
                "/web/support/cases/case-1/transition",
                json={"action": "claim", "note": "telefone pessoal 11999990000"},
                headers=CSRF_HEADERS,
            )

    assert response.status_code == 200
    assert "telefone pessoal" not in caplog.text
    assert "11999990000" not in caplog.text


# --------------------------------------------------------------------------- #
# Fase B: filtro assignee=me
# --------------------------------------------------------------------------- #


def test_assignee_filter_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        _login(client, app)

        response = client.get("/web/support/cases?assignee=everyone")

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_assignee_filter"


def test_assignee_me_filter_resolves_to_logged_in_staff_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        staff_id = _seed_staff(app)
        _login(client, app)
        cursor = FakeCursor(fetchone_results=[], fetchall_results=[[], []])
        app.state.database_runtime = FakeRuntime(cursor)

        response = client.get("/web/support/cases?assignee=me")

    assert response.status_code == 200
    # A fachada resolve "me" para o staff_id da sessao, nunca aceita um id cru
    # vindo do cliente.
    list_sql, list_params = cursor.executed[0]
    assert staff_id in list_params
    assert staff_id != "everyone"


# --------------------------------------------------------------------------- #
# Privacidade dos logs
# --------------------------------------------------------------------------- #


def test_auth_logs_never_leak_phone_code_or_tokens(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        with caplog.at_level(logging.INFO):
            start = client.post(
                "/web/support/auth/start", json={"phone": STAFF_PHONE}
            )
            code = app.state.support_console_runtime.delivery.requests[-1].code
            client.post(
                "/web/support/auth/confirm",
                json={
                    "challenge_id": start.json()["challenge_id"],
                    "code": code,
                    "phone": STAFF_PHONE,
                },
            )
        session_token = client.cookies.get("sfa_staff_session")
        hint_cookie = client.cookies.get("sfa_staff_hint")

    assert STAFF_PHONE not in caplog.text
    assert STAFF_PHONE.lstrip("+") not in caplog.text
    assert code not in caplog.text
    assert session_token not in caplog.text
    assert hint_cookie not in caplog.text
    # Hash sempre truncado: o HMAC completo do telefone nunca aparece.
    assert _hmac_digest(IDENTITY_SECRET, STAFF_PHONE) not in caplog.text


def test_confirm_failure_emits_auth_denied(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        start = client.post("/web/support/auth/start", json={"phone": STAFF_PHONE})
        with caplog.at_level(logging.INFO):
            response = client.post(
                "/web/support/auth/confirm",
                json={"challenge_id": start.json()["challenge_id"], "code": "000000"},
            )
    assert response.status_code == 400
    assert "support_console_auth_denied" in caplog.text
    assert "invalid_or_expired_code" in caplog.text


def test_unauthenticated_case_access_emits_auth_denied(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with _console_client(monkeypatch) as (client, app):
        _seed_staff(app)
        with caplog.at_level(logging.INFO):
            response = client.get("/web/support/cases")
    assert response.status_code == 401
    assert "support_console_auth_denied" in caplog.text
    assert "no_valid_session" in caplog.text


# --------------------------------------------------------------------------- #
# Readiness: combinacao invalida de flags aparece como alerta
# --------------------------------------------------------------------------- #


def _health_runtime(settings: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        pool_enabled=False,
        postgres_required=False,
        persistence_enabled=False,
        retrieval_enabled=False,
        web_auth_enabled=False,
        ingress_enabled=False,
        settings=settings,
    )


def test_readiness_flags_console_without_postgres_persistence() -> None:
    runtime = _health_runtime(
        SimpleNamespace(
            enable_support_console=True,
            persistence_backend="disabled",
            web_auth_otp_delivery_transport="hermes",
            retrieval_backend="lexical",
        )
    )

    report = HealthService(runtime).readiness()

    assert report["components"]["support_console"] == {
        "status": "unavailable",
        "reason": "postgres_persistence_required",
    }
    assert report["status"] == "unavailable"


def test_readiness_flags_console_without_configured_delivery() -> None:
    runtime = _health_runtime(
        SimpleNamespace(
            enable_support_console=True,
            persistence_backend="postgres",
            web_auth_otp_delivery_transport="memory",
            retrieval_backend="lexical",
        )
    )
    # Persistencia postgres com pool desligado nao acontece em producao; aqui
    # so interessa o alerta da entrega.
    runtime.pool_enabled = False

    report = HealthService(runtime).readiness()

    assert report["components"]["support_console"] == {
        "status": "degraded",
        "reason": "otp_delivery_not_configured",
    }


def test_readiness_console_disabled_stays_silent() -> None:
    runtime = _health_runtime(
        SimpleNamespace(
            enable_support_console=False,
            persistence_backend="disabled",
            web_auth_otp_delivery_transport="memory",
            retrieval_backend="lexical",
        )
    )

    report = HealthService(runtime).readiness()

    assert report["components"]["support_console"] == {"status": "disabled"}
    assert report["status"] == "ok"


# --------------------------------------------------------------------------- #
# Config: flag ligada exige segredos
# --------------------------------------------------------------------------- #


def test_console_flag_requires_hash_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "")

    with pytest.raises(ValueError):
        Settings()
