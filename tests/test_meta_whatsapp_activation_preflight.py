from __future__ import annotations

import json

from scripts import meta_whatsapp_activation_preflight as preflight


def test_meta_webhook_ready_when_required_env_is_present() -> None:
    result = preflight.evaluate_mode(
        "meta-webhook",
        {
            "ENABLE_META_WHATSAPP_WEBHOOK": "true",
            "META_WHATSAPP_APP_SECRET": "secret-value",
            "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "verify-token",
        },
    )

    assert result.ready is True
    assert result.missing == ()
    assert result.invalid == ()
    assert "META_WHATSAPP_APP_SECRET" in result.present


def test_meta_chat_detects_disabled_feature_flag_without_printing_value() -> None:
    result = preflight.evaluate_mode(
        "meta-chat",
        {
            "ENABLE_META_WHATSAPP_WEBHOOK": "true",
            "ENABLE_META_WHATSAPP_CHAT": "false",
            "META_WHATSAPP_APP_SECRET": "secret-value",
            "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "verify-token",
            "META_WHATSAPP_ACCESS_TOKEN": "access-token",
            "META_WHATSAPP_PHONE_NUMBER_ID": "phone-id",
        },
    )

    report = preflight.render_report([result], output_format="markdown")

    assert result.ready is False
    assert result.invalid == ("ENABLE_META_WHATSAPP_CHAT",)
    assert "secret-value" not in report
    assert "verify-token" not in report
    assert "access-token" not in report


def test_meta_otp_requires_native_transport_and_template() -> None:
    result = preflight.evaluate_mode(
        "meta-otp",
        {
            "ENABLE_WEB_WHATSAPP_AUTH": "true",
            "IDENTITY_HASH_SECRET": "identity-secret",
            "OTP_DIGEST_SECRET": "otp-secret",
            "WEB_AUTH_OTP_DELIVERY_TRANSPORT": "memory",
            "META_WHATSAPP_ACCESS_TOKEN": "access-token",
            "META_WHATSAPP_PHONE_NUMBER_ID": "phone-id",
        },
    )

    assert result.ready is False
    assert result.invalid == ("WEB_AUTH_OTP_DELIVERY_TRANSPORT",)
    assert result.missing == ("META_WHATSAPP_OTP_TEMPLATE_NAME",)


def test_meta_outbox_message_requires_dispatcher_transport() -> None:
    result = preflight.evaluate_mode(
        "meta-outbox-message",
        {
            "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT": "internal_webhook",
            "META_WHATSAPP_ACCESS_TOKEN": "access-token",
            "META_WHATSAPP_PHONE_NUMBER_ID": "phone-id",
        },
    )

    assert result.ready is False
    assert result.invalid == ("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",)
    assert result.missing == ()
    assert result.recommended_missing == ("META_WHATSAPP_GRAPH_API_VERSION",)


def test_meta_outbox_message_readiness_does_not_require_webhook_secret() -> None:
    result = preflight.evaluate_mode(
        "meta-outbox-message",
        {
            "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT": "meta_whatsapp",
            "META_WHATSAPP_ACCESS_TOKEN": "access-token",
            "META_WHATSAPP_PHONE_NUMBER_ID": "phone-id",
        },
    )

    report = preflight.render_report([result], output_format="json")
    parsed = json.loads(report)

    assert result.ready is True
    assert "OUTBOX_WEBHOOK_SECRET" not in result.missing
    assert "access-token" not in report
    assert parsed["modes"][0]["mode"] == "meta-outbox-message"


def test_hermes_otp_readiness_is_sanitized_json() -> None:
    result = preflight.evaluate_mode(
        "hermes-otp",
        {
            "ENABLE_WEB_WHATSAPP_AUTH": "true",
            "IDENTITY_HASH_SECRET": "identity-secret",
            "OTP_DIGEST_SECRET": "otp-secret",
            "WEB_AUTH_OTP_DELIVERY_TRANSPORT": "hermes",
            "HERMES_BASE_URL": "https://private-hermes.example",
            "HERMES_WEBHOOK_SECRET": "hermes-secret",
        },
    )

    report = preflight.render_report([result], output_format="json")
    parsed = json.loads(report)

    assert parsed["ready"] is True
    assert parsed["modes"][0]["mode"] == "hermes-otp"
    assert "https://private-hermes.example" not in report
    assert "hermes-secret" not in report
    assert "HERMES_OTP_DELIVERY_PATH" in parsed["modes"][0]["recommended_missing"]


def test_main_returns_non_zero_when_mode_is_not_ready(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_activation_preflight.py", "--mode", "meta-webhook"],
    )
    monkeypatch.delenv("ENABLE_META_WHATSAPP_WEBHOOK", raising=False)
    monkeypatch.delenv("META_WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.delenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", raising=False)

    code = preflight.main()
    output = capsys.readouterr()

    assert code == 1
    assert "META_WHATSAPP_APP_SECRET" in output.out
    assert "ready: false" in output.out
