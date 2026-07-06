"""Cobertura da ponte WhatsApp<->console (Fase 1, dark por padrao).

Cobre: token do deep link (auto-verificavel, sem storage), cifra/hash do
wa_id, repositorio de binding, resolucao de caso no inbound (token primario,
hash como fast-path de repeat-contact), thin bot (so responde, nunca inicia),
janela de 24h (best-effort), compositor do atendente e status de entrega.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.integrations.meta_whatsapp.schemas import MetaInboundTextMessage, MetaMessageStatus
from app.support.wa_binding import (
    CaseWhatsAppBinding,
    CaseWhatsAppBindingRepository,
    build_support_deep_link,
    decrypt_wa_id,
    encrypt_wa_id,
    hash_wa_id,
    mint_case_token,
    resolve_case_token,
)
from app.support.whatsapp_bridge import (
    CaseHasNoBinding,
    SupportWhatsAppBridgeService,
    SupportWhatsAppWindowClosed,
    apply_delivery_status,
    is_within_business_hours,
)


# --------------------------------------------------------------------------- #
# Primitivas puras: token, cifra, hash, deep link, horario comercial
# --------------------------------------------------------------------------- #


def test_case_token_round_trips_and_rejects_tamper() -> None:
    case_id = "b3f1c2d4-0000-0000-0000-000000000001"
    token = mint_case_token(case_id, secret="s1")

    assert resolve_case_token(token, secret="s1") == case_id
    assert resolve_case_token(token, secret="wrong-secret") is None
    assert resolve_case_token("garbage", secret="s1") is None
    assert resolve_case_token("", secret="s1") is None
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert resolve_case_token(tampered, secret="s1") is None


def test_wa_id_encryption_round_trips_and_rejects_wrong_key() -> None:
    wa_id = "+5511999999999"
    blob = encrypt_wa_id(wa_id, key="enc-key")

    assert decrypt_wa_id(blob, key="enc-key") == wa_id
    assert decrypt_wa_id(blob, key="different-key") is None


def test_wa_id_hash_is_deterministic_and_key_scoped() -> None:
    h1 = hash_wa_id("+5511999999999", key="k")
    h2 = hash_wa_id("+5511999999999", key="k")
    h3 = hash_wa_id("+5511999999998", key="k")
    h4 = hash_wa_id("+5511999999999", key="other-key")

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_encryption_and_hash_keys_are_domain_separated() -> None:
    """Same operator secret, but the Fernet key and the hash key must be
    derived with different context suffixes, so one primitive's key material
    is never reusable as the other's."""

    import hashlib
    import hmac

    wa_id = "+5511999999999"
    secret = "shared-secret"

    actual_hash = hash_wa_id(wa_id, key=secret)
    hash_using_encrypt_context = hmac.new(
        f"{secret}|encrypt".encode("utf-8"), wa_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    assert actual_hash != hash_using_encrypt_context
    assert decrypt_wa_id(encrypt_wa_id(wa_id, key=secret), key=secret) == wa_id


def test_build_support_deep_link_uses_dialable_number_and_embeds_token() -> None:
    link = build_support_deep_link(
        "b3f1c2d4-0000-0000-0000-000000000001",
        support_phone_e164="+55 11 98888-7777",
        token_secret="s",
    )

    assert link.startswith("https://wa.me/5511988887777?text=")
    assert "case.b3f1c2d4-0000-0000-0000-000000000001." in link


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 7, 6, 13, 0, tzinfo=UTC), True),  # segunda 10:00 BRT
        (datetime(2026, 7, 5, 13, 0, tzinfo=UTC), False),  # domingo
        (datetime(2026, 7, 6, 23, 0, tzinfo=UTC), False),  # segunda 20:00 BRT
        (datetime(2026, 7, 6, 11, 59, tzinfo=UTC), False),  # segunda 08:59 BRT
    ],
)
def test_is_within_business_hours(moment: datetime, expected: bool) -> None:
    assert (
        is_within_business_hours(
            moment,
            timezone_name="America/Sao_Paulo",
            start="09:00",
            end="18:00",
            days="mon,tue,wed,thu,fri",
        )
        is expected
    )


# --------------------------------------------------------------------------- #
# Fakes de DB (mesmo padrao de tests/test_support_transitions.py)
# --------------------------------------------------------------------------- #


class FakeCursor:
    def __init__(self, *, fetchone_results: list | None = None, rowcount: int = 0) -> None:
        self._fetchone = list(fetchone_results) if fetchone_results is not None else []
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    @contextmanager
    def transaction(self):
        yield _Connection(self._cursor)


class _Connection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


ENC_KEY = "test-enc-key"
TOKEN_SECRET = "test-token-secret"
NOW = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# CaseWhatsAppBindingRepository
# --------------------------------------------------------------------------- #


def test_bind_inserts_encrypted_wa_id_and_hash() -> None:
    cursor = FakeCursor(fetchone_results=[])
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    repo.bind(case_id="case-1", wa_id="+5511999999999", max_days=15, now=NOW)

    sql, params = cursor.executed[0]
    assert "INSERT INTO case_whatsapp_bindings" in sql
    case_id, encrypted, wa_hash, bound_at, bound_at2, expires_at = params
    assert case_id == "case-1"
    assert decrypt_wa_id(encrypted, key=ENC_KEY) == "+5511999999999"
    assert wa_hash == hash_wa_id("+5511999999999", key=ENC_KEY)
    assert expires_at == NOW + timedelta(days=15)


def test_get_returns_none_when_no_live_binding() -> None:
    cursor = FakeCursor(fetchone_results=[None])
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    assert repo.get("case-1") is None


def test_get_decrypts_live_binding() -> None:
    encrypted = encrypt_wa_id("+5511999999999", key=ENC_KEY)
    cursor = FakeCursor(fetchone_results=[(encrypted, NOW, NOW, NOW + timedelta(days=15))])
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    binding = repo.get("case-1")

    assert binding is not None
    assert binding.wa_id == "+5511999999999"
    assert binding.case_id == "case-1"


def test_find_open_case_id_by_wa_id_orders_most_recent_first() -> None:
    cursor = FakeCursor(fetchone_results=[("case-recent",)])
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    found = repo.find_open_case_id_by_wa_id("+5511999999999")

    assert found == "case-recent"
    sql, params = cursor.executed[0]
    assert "ORDER BY bound_at DESC" in sql
    assert "LIMIT 1" in sql
    assert params == (hash_wa_id("+5511999999999", key=ENC_KEY),)


def test_find_open_case_id_by_wa_id_none_when_no_match() -> None:
    cursor = FakeCursor(fetchone_results=[None])
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    assert repo.find_open_case_id_by_wa_id("+5511999999999") is None


def test_is_window_open_true_within_hours_false_outside() -> None:
    repo = CaseWhatsAppBindingRepository(FakeRuntime(FakeCursor()), enc_key=ENC_KEY)
    binding = CaseWhatsAppBinding(
        case_id="case-1",
        wa_id="+5511999999999",
        last_customer_message_at=NOW - timedelta(hours=1),
        bound_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(days=14),
    )

    assert repo.is_window_open(binding, window_hours=24, now=NOW) is True
    assert (
        repo.is_window_open(
            binding, window_hours=24, now=NOW + timedelta(hours=25)
        )
        is False
    )


def test_is_window_open_false_when_never_messaged() -> None:
    repo = CaseWhatsAppBindingRepository(FakeRuntime(FakeCursor()), enc_key=ENC_KEY)
    binding = CaseWhatsAppBinding(
        case_id="case-1",
        wa_id="+5511999999999",
        last_customer_message_at=None,
        bound_at=NOW,
        expires_at=NOW + timedelta(days=15),
    )

    assert repo.is_window_open(binding, window_hours=24, now=NOW) is False


def test_unbind_on_close_zeroes_wa_id_and_marks_unbound() -> None:
    cursor = FakeCursor()
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    repo.unbind_on_close("case-1", now=NOW)

    sql, params = cursor.executed[0]
    assert "wa_id_encrypted = '\\x'::bytea" in sql
    assert "unbound_at = %s" in sql
    assert params == (NOW, "case-1")


def test_purge_expired_returns_rowcount() -> None:
    cursor = FakeCursor(rowcount=3)
    repo = CaseWhatsAppBindingRepository(FakeRuntime(cursor), enc_key=ENC_KEY)

    purged = repo.purge_expired(now=NOW)

    assert purged == 3
    sql, _ = cursor.executed[0]
    assert "expires_at <= %s" in sql


# --------------------------------------------------------------------------- #
# SupportWhatsAppBridgeService - resolucao de caso e thin bot
# --------------------------------------------------------------------------- #


@dataclass
class FakeBindings:
    """Duck-typed stand-in for CaseWhatsAppBindingRepository -- lets the
    service tests focus on authorization/business logic without a DB fake
    for the binding table itself."""

    open_case_by_wa_id: str | None = None
    existing_get: object | None = None
    bind_calls: list[dict] = field(default_factory=list)
    touch_calls: list[dict] = field(default_factory=list)

    def find_open_case_id_by_wa_id(self, wa_id: str) -> str | None:
        return self.open_case_by_wa_id

    def get(self, case_id: str):
        return self.existing_get

    def bind(self, *, case_id, wa_id, max_days, now):
        self.bind_calls.append({"case_id": case_id, "wa_id": wa_id, "max_days": max_days})

    def touch_customer_message(self, *, case_id, now):
        self.touch_calls.append({"case_id": case_id})

    def is_window_open(self, binding, *, window_hours, now=None) -> bool:
        return True


@dataclass
class FakeMetaClient:
    sent: list[dict] = field(default_factory=list)

    def send_text(self, *, to: str, text: str):
        self.sent.append({"to": to, "text": text})
        return SimpleNamespace(message_id="wamid.fake")


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        support_wa_token_secret=TOKEN_SECRET,
        support_wa_binding_max_days=15,
        support_wa_window_hours=24,
        support_console_timezone="America/Sao_Paulo",
        support_business_hours_start="09:00",
        support_business_hours_end="18:00",
        support_business_days="mon,tue,wed,thu,fri",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(text: str, *, from_wa_id: str = "5511999999999") -> MetaInboundTextMessage:
    return MetaInboundTextMessage(
        message_id="wamid.1", from_wa_id=from_wa_id, timestamp=None, text=text
    )


MONDAY_10AM_BRT = datetime(2026, 7, 6, 13, 0, tzinfo=UTC)


def test_handle_inbound_unmatched_sends_not_found_and_touches_nothing() -> None:
    cursor = FakeCursor()
    bindings = FakeBindings(open_case_by_wa_id=None)
    client = FakeMetaClient()
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=client,
        bindings=bindings,
    )

    result = service.handle_inbound(_message("oi"), request_id="req-1")

    assert result.case_id is None
    assert result.bound is False
    assert len(client.sent) == 1
    assert "Nao encontrei" in client.sent[0]["text"]
    assert cursor.executed == []  # numero handoff-only: sem triagem, sem escrita


CASE_UUID = "b3f1c2d4-0000-0000-0000-000000000001"


def test_handle_inbound_rejects_token_to_closed_case() -> None:
    """Regression guard: the token must round-trip through the regex
    extractor (UUID-shaped case ids) for this to actually exercise the
    closed-status rejection, not just a malformed-token no-op."""

    token = mint_case_token(CASE_UUID, secret=TOKEN_SECRET)
    assert token in f"Atendimento: {token}"  # extractable shape, sanity check
    cursor = FakeCursor(fetchone_results=[("closed",)])
    bindings = FakeBindings(open_case_by_wa_id=None)
    client = FakeMetaClient()
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=client,
        bindings=bindings,
    )

    result = service.handle_inbound(
        _message(f"Atendimento: {token}"), request_id="req-1"
    )

    assert result.case_id is None
    assert "Nao encontrei" in client.sent[0]["text"]
    # A rejeicao veio do status 'closed' (SELECT consumido), nao de token malformado.
    assert cursor.executed  # o SELECT support_cases.status foi executado


def test_handle_inbound_first_contact_binds_appends_and_acks() -> None:
    token = mint_case_token(CASE_UUID, secret=TOKEN_SECRET)
    cursor = FakeCursor(
        fetchone_results=[
            ("open",),  # _case_is_open
            ("conv-1", "open"),  # _append_message: SELECT support_cases
            ("msg-1",),  # _append_message: INSERT messages RETURNING id
        ]
    )
    bindings = FakeBindings(open_case_by_wa_id=None, existing_get=None)
    client = FakeMetaClient()
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=client,
        bindings=bindings,
        now=lambda: MONDAY_10AM_BRT,
    )

    result = service.handle_inbound(
        _message(f"Atendimento: {token}", from_wa_id="5511988887777"),
        request_id="req-1",
    )

    assert result.case_id == CASE_UUID
    assert result.bound is True
    assert result.acked is True
    assert bindings.bind_calls == [
        {"case_id": CASE_UUID, "wa_id": "5511988887777", "max_days": 15}
    ]
    assert bindings.touch_calls == [{"case_id": CASE_UUID}]
    assert len(client.sent) == 1
    assert "atendente" in client.sent[0]["text"].lower()
    # append_case_message + human_active + event, todas na mesma transacao logica
    insert_messages = [sql for sql, _ in cursor.executed if "INSERT INTO messages" in sql]
    assert len(insert_messages) == 1
    events = [sql for sql, _ in cursor.executed if "INSERT INTO support_case_events" in sql]
    assert len(events) == 1


def test_handle_inbound_repeat_contact_within_hours_does_not_ack() -> None:
    cursor = FakeCursor(
        fetchone_results=[
            ("open",),  # _case_is_open
            ("conv-1", "open"),  # _append_message
            ("msg-2",),
        ]
    )
    bindings = FakeBindings(
        open_case_by_wa_id="case-1", existing_get=object()
    )
    client = FakeMetaClient()
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=client,
        bindings=bindings,
        now=lambda: MONDAY_10AM_BRT,
    )

    result = service.handle_inbound(_message("obrigado!"), request_id="req-1")

    assert result.case_id == "case-1"
    assert result.acked is False
    assert client.sent == []


def test_handle_inbound_out_of_hours_still_acks_with_hours_suffix() -> None:
    cursor = FakeCursor(
        fetchone_results=[("open",), ("conv-1", "open"), ("msg-3",)]
    )
    bindings = FakeBindings(open_case_by_wa_id="case-1", existing_get=object())
    client = FakeMetaClient()
    sunday = datetime(2026, 7, 5, 13, 0, tzinfo=UTC)
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=client,
        bindings=bindings,
        now=lambda: sunday,
    )

    result = service.handle_inbound(_message("alguem ai?"), request_id="req-1")

    assert result.acked is True
    assert "atende de" in client.sent[0]["text"]


# --------------------------------------------------------------------------- #
# send_agent_reply (compositor do console)
# --------------------------------------------------------------------------- #


def test_send_agent_reply_raises_when_no_binding() -> None:
    bindings = FakeBindings(existing_get=None)
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(FakeCursor()),
        client=FakeMetaClient(),
        bindings=bindings,
    )

    with pytest.raises(CaseHasNoBinding):
        service.send_agent_reply(case_id="case-1", staff_id="staff-1", text="oi")


def test_send_agent_reply_raises_when_window_closed() -> None:
    class ClosedWindowBindings(FakeBindings):
        def is_window_open(self, binding, *, window_hours, now=None) -> bool:
            return False

    bindings = ClosedWindowBindings(existing_get=object())
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(FakeCursor()),
        client=FakeMetaClient(),
        bindings=bindings,
    )

    with pytest.raises(SupportWhatsAppWindowClosed):
        service.send_agent_reply(case_id="case-1", staff_id="staff-1", text="oi")


def test_send_agent_reply_appends_message_and_enqueues_outbox() -> None:
    binding = CaseWhatsAppBinding(
        case_id="case-1",
        wa_id="+5511999999999",
        last_customer_message_at=NOW,
        bound_at=NOW,
        expires_at=NOW + timedelta(days=15),
    )
    cursor = FakeCursor(
        fetchone_results=[
            ("conv-1", "in_progress"),  # _append_message: SELECT support_cases
            ("msg-agent-1",),  # INSERT messages RETURNING id
            # _enqueue_send's INSERT has no RETURNING -> no fetchone needed
        ]
    )
    bindings = FakeBindings(existing_get=binding)
    service = SupportWhatsAppBridgeService(
        settings=_settings(),
        database_runtime=FakeRuntime(cursor),
        client=FakeMetaClient(),
        bindings=bindings,
    )

    result = service.send_agent_reply(
        case_id="case-1", staff_id="staff-1", text="Resolvido, pode confirmar?"
    )

    assert result.message_id == "msg-agent-1"
    outbox_inserts = [
        (sql, params)
        for sql, params in cursor.executed
        if "INSERT INTO operational_outbox" in sql
    ]
    assert len(outbox_inserts) == 1
    _, params = outbox_inserts[0]
    idempotency_key, request_id, payload = params
    assert idempotency_key == "support_wa_send:msg-agent-1"
    assert request_id == "case-1"
    assert '"phone_number_kind": "support"' in payload
    assert '"to": "+5511999999999"' in payload
    assert '"message_row_id": "msg-agent-1"' in payload
    events = [sql for sql, _ in cursor.executed if "INSERT INTO support_case_events" in sql]
    assert len(events) == 1


# --------------------------------------------------------------------------- #
# apply_delivery_status (webhook de status da Meta)
# --------------------------------------------------------------------------- #


def test_apply_delivery_status_unknown_message_id_returns_false() -> None:
    cursor = FakeCursor(fetchone_results=[None])
    status = MetaMessageStatus(
        message_id="wamid.unknown", status="delivered", timestamp=None, recipient_id=None
    )

    assert apply_delivery_status(FakeRuntime(cursor), status) is False


def test_apply_delivery_status_advances_rank() -> None:
    cursor = FakeCursor(fetchone_results=[("sent",)])
    status = MetaMessageStatus(
        message_id="wamid.1", status="delivered", timestamp=None, recipient_id=None
    )

    assert apply_delivery_status(FakeRuntime(cursor), status) is True
    update_sql, params = cursor.executed[1]
    assert "UPDATE messages" in update_sql
    assert params == ("delivered", "wamid.1")


def test_apply_delivery_status_ignores_out_of_order_earlier_status() -> None:
    cursor = FakeCursor(fetchone_results=[("delivered",)])
    status = MetaMessageStatus(
        message_id="wamid.1", status="sent", timestamp=None, recipient_id=None
    )

    assert apply_delivery_status(FakeRuntime(cursor), status) is False
    assert len(cursor.executed) == 1  # so o SELECT, nenhum UPDATE


def test_apply_delivery_status_failed_always_overwrites() -> None:
    cursor = FakeCursor(fetchone_results=[("read",)])
    status = MetaMessageStatus(
        message_id="wamid.1", status="failed", timestamp=None, recipient_id=None
    )

    assert apply_delivery_status(FakeRuntime(cursor), status) is True
