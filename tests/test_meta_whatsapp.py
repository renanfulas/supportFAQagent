from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings, get_settings
from app.domain_engine.models import DomainConfig
from app.integrations.meta_whatsapp.client import (
    MetaWhatsAppClient,
    MetaWhatsAppRequestError,
)
from app.integrations.meta_whatsapp.chat_transport import MetaWhatsAppChatTransport
from app.integrations.meta_whatsapp.chat_transport import MetaWhatsAppChatTransportError
from app.integrations.meta_whatsapp.otp_delivery import MetaWhatsAppOtpDeliveryAdapter
from app.integrations.meta_whatsapp.schemas import (
    MetaInboundTextMessage,
    MetaSendResult,
    parse_webhook_payload,
)
from app.integrations.meta_whatsapp.webhook import verify_meta_signature
from app.main import create_app
from app.db.operational import ChatPersistenceResult
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.models import OtpDeliveryRequest
from app.web_auth.runtime import create_web_auth_runtime
from app.api.routes.meta_whatsapp import _safe_meta_error_detail


APP_SECRET = "meta-app-secret"


def _signature(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_meta_webhook_signature_validation() -> None:
    body = b'{"object":"whatsapp_business_account"}'

    assert verify_meta_signature(
        body=body,
        signature=_signature(body),
        app_secret=APP_SECRET,
    )
    assert not verify_meta_signature(
        body=body,
        signature="sha256=invalid",
        app_secret=APP_SECRET,
    )


def test_meta_webhook_parser_extracts_text_messages_and_statuses() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "5511999999999",
                                    "id": "wamid.inbound",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "Oi"},
                                },
                                {
                                    "from": "5511888888888",
                                    "id": "wamid.image",
                                    "type": "image",
                                },
                            ],
                            "statuses": [
                                {
                                    "id": "wamid.outbound",
                                    "status": "delivered",
                                    "timestamp": "1710000001",
                                    "recipient_id": "5511999999999",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    parsed = parse_webhook_payload(payload)

    assert len(parsed.messages) == 1
    assert parsed.messages[0].message_id == "wamid.inbound"
    assert parsed.messages[0].text == "Oi"
    assert len(parsed.statuses) == 1
    assert parsed.statuses[0].status == "delivered"


def test_meta_webhook_settings_require_secret_and_verify_token_when_enabled() -> None:
    with pytest.raises(ValueError, match="META_WHATSAPP_APP_SECRET"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            ENABLE_META_WHATSAPP_WEBHOOK="true",
            META_WHATSAPP_WEBHOOK_VERIFY_TOKEN="verify-token",
        )


def test_meta_webhook_verification_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/integrations/meta/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-value"
    get_settings.cache_clear()


def test_meta_webhook_verification_rejects_wrong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/integrations/meta/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 403
    get_settings.cache_clear()


def test_meta_webhook_post_rejects_invalid_signature_before_logging_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    get_settings.cache_clear()
    client = TestClient(create_app())
    body = b'{"entry":[{"changes":[{"value":{"messages":[{"from":"5511999999999","id":"wamid.inbound","type":"text","text":{"body":"telefone +5511999999999"}}]}}]}]}'

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/integrations/meta/whatsapp/webhook",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )

    assert response.status_code == 401
    assert "+5511999999999" not in caplog.text
    get_settings.cache_clear()


def test_meta_webhook_post_accepts_signed_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    get_settings.cache_clear()
    client = TestClient(create_app())
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5511999999999",
                                        "id": "wamid.inbound",
                                        "type": "text",
                                        "text": {"body": "Oi"},
                                    }
                                ],
                                "statuses": [{"id": "wamid.out", "status": "sent"}],
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/integrations/meta/whatsapp/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body)},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert "messages_count" in caplog.text
    assert "5511999999999" not in caplog.text
    get_settings.cache_clear()


def test_meta_webhook_chat_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("ENABLE_META_WHATSAPP_CHAT", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    get_settings.cache_clear()

    class FailingTransport:
        def __init__(self, **kwargs) -> None:
            return None

        def handle_text_message(self, **kwargs) -> None:
            raise RuntimeError("provider failed token=secret +5511999999999")

    monkeypatch.setattr(
        "app.api.routes.meta_whatsapp.MetaWhatsAppChatTransport",
        FailingTransport,
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5511999999999",
                                        "id": "wamid.inbound",
                                        "type": "text",
                                        "text": {"body": "Oi token=secret"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/integrations/meta/whatsapp/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _signature(body)},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "meta_whatsapp_chat_processing_failed"
    assert "token=secret" not in response.text
    assert "+5511999999999" not in response.text
    assert "token=secret" not in caplog.text
    assert "+5511999999999" not in caplog.text
    assert "RuntimeError" in caplog.text
    get_settings.cache_clear()


def test_meta_webhook_chat_transport_error_detail_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_META_WHATSAPP_WEBHOOK", "true")
    monkeypatch.setenv("ENABLE_META_WHATSAPP_CHAT", "true")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    get_settings.cache_clear()

    class FailingTransport:
        def __init__(self, **kwargs) -> None:
            return None

        def handle_text_message(self, **kwargs) -> None:
            raise MetaWhatsAppChatTransportError("provider token=secret +5511999999999")

    monkeypatch.setattr(
        "app.api.routes.meta_whatsapp.MetaWhatsAppChatTransport",
        FailingTransport,
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    body = json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5511999999999",
                                        "id": "wamid.inbound",
                                        "type": "text",
                                        "text": {"body": "Oi"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
        separators=(",", ":"),
    ).encode()

    response = client.post(
        "/integrations/meta/whatsapp/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _signature(body)},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "meta_whatsapp_chat_processing_failed"
    assert "token=secret" not in response.text
    assert "+5511999999999" not in response.text
    get_settings.cache_clear()


def test_safe_meta_error_detail_allows_only_internal_codes() -> None:
    assert _safe_meta_error_detail("meta_whatsapp_domain_not_found") == "meta_whatsapp_domain_not_found"
    assert (
        _safe_meta_error_detail("provider token=secret +5511999999999")
        == "meta_whatsapp_chat_processing_failed"
    )


def test_meta_client_sends_text_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "contacts": [{"wa_id": "5511999999999"}],
                "messages": [{"id": "wamid.outbound"}],
            }

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.integrations.meta_whatsapp.client.requests.post", fake_post)
    client = MetaWhatsAppClient(
        access_token="token",
        phone_number_id="phone-id",
        graph_api_version="v25.0",
        timeout_seconds=7,
    )

    result = client.send_text(to="5511999999999", text="Oi")

    assert captured["url"] == "https://graph.facebook.com/v25.0/phone-id/messages"
    assert captured["json"]["messaging_product"] == "whatsapp"
    assert captured["json"]["type"] == "text"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["timeout"] == 7
    assert result.message_id == "wamid.outbound"


def test_meta_client_sanitizes_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 400

        def raise_for_status(self) -> None:
            import requests

            raise requests.HTTPError(
                "private provider body with token",
                response=self,
            )

    monkeypatch.setattr(
        "app.integrations.meta_whatsapp.client.requests.post",
        lambda *args, **kwargs: Response(),
    )
    client = MetaWhatsAppClient(
        access_token="token",
        phone_number_id="phone-id",
        graph_api_version="v25.0",
    )

    with pytest.raises(MetaWhatsAppRequestError) as exc_info:
        client.send_text(to="5511999999999", text="Oi")

    assert str(exc_info.value) == "meta_whatsapp_request_failed"
    assert exc_info.value.status_code == 400
    assert "token" not in str(exc_info.value)


def test_meta_otp_delivery_adapter_sends_template() -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def send_template(self, **kwargs):
            captured.update(kwargs)

    adapter = MetaWhatsAppOtpDeliveryAdapter(
        client=FakeClient(),
        template_name="web_login_otp",
        language_code="pt_BR",
    )

    adapter.deliver(
        OtpDeliveryRequest(
            challenge_id="challenge-id",
            phone="+5511999999999",
            code="123456",
            expires_in_seconds=300,
        )
    )

    assert captured["to"] == "+5511999999999"
    assert captured["template_name"] == "web_login_otp"
    assert captured["language_code"] == "pt_BR"
    assert captured["components"][0]["parameters"][0]["text"] == "123456"
    assert captured["components"][0]["parameters"][1]["text"] == "5"


def test_meta_otp_delivery_adapter_sanitizes_failures() -> None:
    class FakeClient:
        def send_template(self, **kwargs):
            raise MetaWhatsAppRequestError("private provider body with token")

    adapter = MetaWhatsAppOtpDeliveryAdapter(
        client=FakeClient(),
        template_name="web_login_otp",
        language_code="pt_BR",
    )

    with pytest.raises(OtpDeliveryUnavailable) as exc_info:
        adapter.deliver(
            OtpDeliveryRequest(
                challenge_id="challenge-id",
                phone="+5511999999999",
                code="123456",
                expires_in_seconds=300,
            )
        )

    assert str(exc_info.value) == "meta_whatsapp_delivery_failed"
    assert "token" not in str(exc_info.value)


def test_web_auth_runtime_selects_meta_otp_delivery_when_enabled() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WEB_WHATSAPP_AUTH="true",
        IDENTITY_HASH_SECRET="identity-secret",
        OTP_DIGEST_SECRET="otp-secret",
        WEB_AUTH_OTP_DELIVERY_TRANSPORT="meta",
        META_WHATSAPP_ACCESS_TOKEN="token",
        META_WHATSAPP_PHONE_NUMBER_ID="phone-id",
        META_WHATSAPP_OTP_TEMPLATE_NAME="web_login_otp",
    )

    runtime = create_web_auth_runtime(settings)

    assert isinstance(runtime.delivery, MetaWhatsAppOtpDeliveryAdapter)


def test_web_auth_meta_otp_transport_requires_meta_credentials() -> None:
    with pytest.raises(ValueError, match="META_WHATSAPP_ACCESS_TOKEN"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            ENABLE_WEB_WHATSAPP_AUTH="true",
            IDENTITY_HASH_SECRET="identity-secret",
            OTP_DIGEST_SECRET="otp-secret",
            WEB_AUTH_OTP_DELIVERY_TRANSPORT="meta",
            META_WHATSAPP_PHONE_NUMBER_ID="phone-id",
            META_WHATSAPP_OTP_TEMPLATE_NAME="web_login_otp",
        )


def test_meta_chat_transport_calls_core_without_raw_wa_id() -> None:
    captured: dict[str, object] = {}
    settings = Settings(_env_file=None, APP_ENV="development")

    class FakeDomainLoader:
        def load(self, domain_name: str):
            captured["domain_name"] = domain_name
            return DomainConfig(
                name=domain_name, display_name=domain_name, root_path=Path(".")
            )

    class FakeChatService:
        def answer(self, **kwargs):
            captured["chat_kwargs"] = kwargs
            return {
                "domain": "suporte-vps-whatsapp",
                "answer": "Resposta segura.",
                "confidence": 0.9,
                "escalated": False,
                "handoff_reasons": [],
                "references": ["safe.md"],
                "error_code": None,
            }

    class FakeRepository:
        def record_chat(self, audit):
            captured["audit"] = audit
            return ChatPersistenceResult(
                handoff_status="handoff_not_required",
                persistence_status="persisted",
                turn_id="turn-id",
            )

    class FakeClient:
        def send_text(self, *, to: str, text: str) -> MetaSendResult:
            captured["outbound_to"] = to
            captured["outbound_text"] = text
            return MetaSendResult(message_id="wamid.outbound")

    transport = MetaWhatsAppChatTransport(
        settings=settings,
        database_runtime=object(),
        client=FakeClient(),
        domain_loader=FakeDomainLoader(),
        chat_service=FakeChatService(),
        repository=FakeRepository(),
    )

    result = transport.handle_text_message(
        message=MetaInboundTextMessage(
            message_id="wamid.inbound",
            from_wa_id="5511999999999",
            timestamp="1710000000",
            text="Oi",
        ),
        request_id="meta-chat-req",
    )

    chat_kwargs = captured["chat_kwargs"]
    audit = captured["audit"]
    assert chat_kwargs["channel"] == "whatsapp"
    assert chat_kwargs["question"] == "Oi"
    assert chat_kwargs["session_id"].startswith("whatsapp:meta:")
    assert "5511999999999" not in chat_kwargs["session_id"]
    assert audit.session_id == chat_kwargs["session_id"]
    assert audit.channel == "whatsapp"
    assert captured["outbound_to"] == "5511999999999"
    assert captured["outbound_text"] == "Resposta segura."
    assert result.outbound_message_id == "wamid.outbound"


def test_meta_chat_transport_settings_require_send_credentials() -> None:
    with pytest.raises(ValueError, match="META_WHATSAPP_ACCESS_TOKEN"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            ENABLE_META_WHATSAPP_CHAT="true",
            META_WHATSAPP_PHONE_NUMBER_ID="phone-id",
        )
