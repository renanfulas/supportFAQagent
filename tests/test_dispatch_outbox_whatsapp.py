"""Ponte WhatsApp<->console: seletor de numero e escrita do status de entrega
no dispatcher do outbox (``scripts/dispatch_outbox.py``).

Modo-por-numero no envio: ``phone_number_kind`` no payload decide qual
``phone_number_id`` (numero bot vs numero de suporte) o dispatcher usa --
mesmo access token/WABA, so o numero muda. Apos um envio bem-sucedido com
``message_row_id`` no payload, o ``meta_message_id`` retornado pela Meta e
gravado de volta na linha de ``messages`` correspondente (para o webhook de
status de entrega correlacionar depois).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from scripts.dispatch_outbox import (
    DeliveryResult,
    DeliveryRoute,
    PermanentDeliveryError,
    _maybe_record_message_delivery,
    deliver,
    deliver_meta_whatsapp,
    deliver_meta_whatsapp_template,
    resolve_delivery_route,
    resolve_delivery_transport,
)


@dataclass
class RecordingClient:
    calls: list = field(default_factory=list)

    def send_text(self, *, to: str, text: str):
        self.calls.append({"to": to, "text": text})
        return SimpleNamespace(message_id="wamid.sent-1")


ROUTE = DeliveryRoute(
    name="whatsapp_message",
    url_env="WHATSAPP_MESSAGE_WEBHOOK_URL",
    transport_env="OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
)


def _patch_client(monkeypatch: pytest.MonkeyPatch, recorder: RecordingClient) -> dict:
    """Bypass the real dataclass __init__ (no HTTP call, no attribute access
    needed) while still capturing the kwargs the dispatcher constructed it
    with -- that's what proves which phone_number_id was selected."""

    captured_kwargs: dict = {}
    monkeypatch.setattr(
        MetaWhatsAppClient,
        "__init__",
        lambda self, **kw: captured_kwargs.update(kw) or None,
    )
    monkeypatch.setattr(
        MetaWhatsAppClient, "send_text", lambda self, **kw: recorder.send_text(**kw)
    )
    return captured_kwargs


def test_deliver_meta_whatsapp_uses_support_number_when_kind_is_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "shared-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "bot-number-id")
    monkeypatch.setenv("META_SUPPORT_PHONE_NUMBER_ID", "support-number-id")
    recorder = RecordingClient()
    captured = _patch_client(monkeypatch, recorder)

    event = {
        "payload_sanitized": {
            "to": "+5511999999999",
            "text": "Resolvido, pode confirmar?",
            "phone_number_kind": "support",
            "message_row_id": "msg-1",
        }
    }

    result = deliver_meta_whatsapp(event=event, route=ROUTE)

    assert captured["phone_number_id"] == "support-number-id"
    assert captured["access_token"] == "shared-token"
    assert recorder.calls == [{"to": "+5511999999999", "text": "Resolvido, pode confirmar?"}]
    assert result.meta_message_id == "wamid.sent-1"


def test_deliver_meta_whatsapp_defaults_to_bot_number_without_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "shared-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "bot-number-id")
    monkeypatch.setenv("META_SUPPORT_PHONE_NUMBER_ID", "support-number-id")
    recorder = RecordingClient()
    captured = _patch_client(monkeypatch, recorder)

    event = {
        "payload_sanitized": {
            "to": "+5511988887777",
            "text": "Novo atendimento humano...",
        }
    }

    deliver_meta_whatsapp(event=event, route=ROUTE)

    assert captured["phone_number_id"] == "bot-number-id"


def test_deliver_meta_whatsapp_support_kind_requires_support_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "shared-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "bot-number-id")
    monkeypatch.delenv("META_SUPPORT_PHONE_NUMBER_ID", raising=False)

    event = {
        "payload_sanitized": {
            "to": "+5511999999999",
            "text": "oi",
            "phone_number_kind": "support",
        }
    }

    with pytest.raises(RuntimeError, match="META_SUPPORT_PHONE_NUMBER_ID"):
        deliver_meta_whatsapp(event=event, route=ROUTE)


# --------------------------------------------------------------------------- #
# Escrita do meta_message_id de volta em messages (correlacao p/ status)
# --------------------------------------------------------------------------- #


class RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))


def test_maybe_record_message_delivery_writes_meta_message_id() -> None:
    cursor = RecordingCursor()
    event = {
        "payload_sanitized": {
            "to": "+5511999999999",
            "text": "oi",
            "message_row_id": "msg-1",
        }
    }
    _maybe_record_message_delivery(
        cursor, event=event, result=DeliveryResult(meta_message_id="wamid.sent-1")
    )

    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "UPDATE messages" in sql
    assert params == ("wamid.sent-1", "msg-1")


def test_maybe_record_message_delivery_noop_without_message_row_id() -> None:
    cursor = RecordingCursor()
    event = {"payload_sanitized": {"to": "+5511999999999", "text": "oi"}}
    _maybe_record_message_delivery(
        cursor, event=event, result=DeliveryResult(meta_message_id="wamid.sent-1")
    )

    assert cursor.executed == []


def test_maybe_record_message_delivery_noop_when_send_had_no_message_id() -> None:
    cursor = RecordingCursor()
    event = {
        "payload_sanitized": {
            "to": "+5511999999999",
            "text": "oi",
            "message_row_id": "msg-1",
        }
    }
    _maybe_record_message_delivery(cursor, event=event, result=DeliveryResult())

    assert cursor.executed == []


# --------------------------------------------------------------------------- #
# Fase 2: templates + rota de e-mail (so enfileira, sem transporte real)
# --------------------------------------------------------------------------- #


@dataclass
class RecordingTemplateClient:
    calls: list = field(default_factory=list)

    def send_template(self, *, to: str, template_name: str, language_code: str, components):
        self.calls.append(
            {
                "to": to,
                "template_name": template_name,
                "language_code": language_code,
                "components": components,
            }
        )
        return SimpleNamespace(message_id="wamid.template-1")


TEMPLATE_ROUTE = DeliveryRoute(
    name="whatsapp_template",
    url_env="WHATSAPP_TEMPLATE_WEBHOOK_URL",
    transport_env="OUTBOX_WHATSAPP_TEMPLATE_DELIVERY_TRANSPORT",
)


def test_deliver_meta_whatsapp_template_uses_support_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "shared-token")
    monkeypatch.setenv("META_SUPPORT_PHONE_NUMBER_ID", "support-number-id")
    recorder = RecordingTemplateClient()
    captured: dict = {}
    monkeypatch.setattr(
        MetaWhatsAppClient,
        "__init__",
        lambda self, **kw: captured.update(kw) or None,
    )
    monkeypatch.setattr(
        MetaWhatsAppClient,
        "send_template",
        lambda self, **kw: recorder.send_template(**kw),
    )

    event = {
        "payload_sanitized": {
            "to": "+5511999999999",
            "template_name": "ticket_resolvido",
            "language_code": "pt_BR",
            "phone_number_kind": "support",
            "message_row_id": "msg-1",
        }
    }

    result = deliver_meta_whatsapp_template(event=event, route=TEMPLATE_ROUTE)

    assert captured["phone_number_id"] == "support-number-id"
    assert recorder.calls == [
        {
            "to": "+5511999999999",
            "template_name": "ticket_resolvido",
            "language_code": "pt_BR",
            "components": None,
        }
    ]
    assert result.meta_message_id == "wamid.template-1"


def test_deliver_meta_whatsapp_template_wrong_route_is_permanent_error() -> None:
    event = {"payload_sanitized": {"to": "x", "template_name": "y", "language_code": "pt_BR"}}
    wrong_route = DeliveryRoute(
        name="whatsapp_message",
        url_env="WHATSAPP_MESSAGE_WEBHOOK_URL",
        transport_env="OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
    )
    with pytest.raises(PermanentDeliveryError):
        deliver_meta_whatsapp_template(event=event, route=wrong_route)


def test_email_route_defaults_to_disabled_and_never_sends() -> None:
    """Fase 2 decision: enqueue only, no real transport yet -- the existing
    'disabled' guard in deliver() covers this without inventing a provider."""

    route = resolve_delivery_route("email.message.requested")
    assert route.name == "email"
    assert resolve_delivery_transport(route) == "disabled"

    with pytest.raises(PermanentDeliveryError, match="delivery route is disabled: email"):
        deliver(
            {
                "event_type": "email.message.requested",
                "payload_sanitized": {
                    "to": "cliente@example.com",
                    "subject": "Seu chamado foi resolvido",
                    "body": "...",
                },
            }
        )


def test_email_route_can_be_overridden_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Juliano ligando o provedor de verdade so precisa setar o transport_env
    -- nao muda nenhum codigo aqui."""

    monkeypatch.setenv("OUTBOX_EMAIL_DELIVERY_TRANSPORT", "internal_webhook")
    route = resolve_delivery_route("email.message.requested")
    assert resolve_delivery_transport(route) == "internal_webhook"
