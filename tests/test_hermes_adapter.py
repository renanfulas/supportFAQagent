from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.core.config import Settings
from app.integrations.hermes.client import HermesClient, HermesRequestError
from app.integrations.hermes.otp_delivery import HermesOtpDeliveryAdapter
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.models import OtpDeliveryRequest
from app.web_auth.runtime import create_web_auth_runtime


def test_hermes_client_signs_otp_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, *, data, headers, timeout):
        captured.update(url=url, data=data, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.integrations.hermes.client.requests.post", fake_post)
    client = HermesClient(
        base_url="https://hermes.internal",
        webhook_secret="hermes-secret",
        timeout_seconds=7,
    )

    client.deliver_otp(
        {
            "delivery_id": "challenge-id",
            "channel": "whatsapp",
            "phone_e164": "+5511999999999",
        },
        delivery_id="challenge-id",
    )

    assert captured["url"] == "https://hermes.internal/otp-delivery"
    assert captured["timeout"] == 7
    headers = captured["headers"]
    assert headers["X-Delivery-ID"] == "challenge-id"
    assert not headers["X-Webhook-Signature"].startswith("sha256=")
    body = captured["data"]
    timestamp = headers["X-Webhook-Timestamp"]
    expected = hmac.new(
        b"hermes-secret",
        body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Webhook-Signature"] == expected


def test_hermes_otp_delivery_adapter_sends_only_transport_payload() -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def deliver_otp(self, payload, *, delivery_id):
            captured["payload"] = payload
            captured["delivery_id"] = delivery_id

    adapter = HermesOtpDeliveryAdapter(
        client=FakeClient(),
        template_name="web_login_otp",
    )

    adapter.deliver(
        OtpDeliveryRequest(
            challenge_id="challenge-id",
            phone="+5511999999999",
            code="123456",
            expires_in_seconds=300,
        )
    )

    payload = captured["payload"]
    assert captured["delivery_id"] == "challenge-id"
    assert payload == {
        "delivery_id": "challenge-id",
        "channel": "whatsapp",
        "phone_e164": "+5511999999999",
        "chat_id": "5511999999999@s.whatsapp.net",
        "template": "web_login_otp",
        "variables": {"code": "123456", "expires_in_minutes": 5},
    }
    assert "prompt" not in json.dumps(payload)
    assert "handoff" not in json.dumps(payload)
    assert "database" not in json.dumps(payload)


def test_hermes_otp_delivery_adapter_sanitizes_failures() -> None:
    class FakeClient:
        def deliver_otp(self, payload, *, delivery_id):
            raise HermesRequestError("private provider detail with token")

    adapter = HermesOtpDeliveryAdapter(
        client=FakeClient(),
        template_name="web_login_otp",
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

    assert str(exc_info.value) == "hermes_delivery_failed"
    assert "token" not in str(exc_info.value)


def test_web_auth_runtime_selects_hermes_otp_delivery_when_enabled() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WEB_WHATSAPP_AUTH="true",
        IDENTITY_HASH_SECRET="identity-secret",
        OTP_DIGEST_SECRET="otp-secret",
        WEB_AUTH_OTP_DELIVERY_TRANSPORT="hermes",
        HERMES_BASE_URL="https://hermes.internal",
        HERMES_WEBHOOK_SECRET="hermes-secret",
    )

    runtime = create_web_auth_runtime(settings)

    assert isinstance(runtime.delivery, HermesOtpDeliveryAdapter)


def test_web_auth_hermes_transport_requires_private_config() -> None:
    with pytest.raises(ValueError, match="HERMES_BASE_URL"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            ENABLE_WEB_WHATSAPP_AUTH="true",
            IDENTITY_HASH_SECRET="identity-secret",
            OTP_DIGEST_SECRET="otp-secret",
            WEB_AUTH_OTP_DELIVERY_TRANSPORT="hermes",
            HERMES_WEBHOOK_SECRET="hermes-secret",
        )


def test_hermes_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="HERMES_OTP_DELIVERY_PATH"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            HERMES_OTP_DELIVERY_PATH="otp-delivery",
        )
