from __future__ import annotations

import json
import subprocess
import sys

from scripts import meta_whatsapp_private_smoke as smoke


def test_meta_signature_uses_app_secret() -> None:
    body = b'{"safe":"payload"}'

    signature = smoke.meta_signature(body, "app-secret")

    assert signature.startswith("sha256=")
    assert smoke.meta_signature(body, "other-secret") != signature


def test_missing_env_reports_names_without_values(monkeypatch) -> None:
    monkeypatch.delenv("META_WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "private-token")

    assert smoke.missing_env(
        "META_WHATSAPP_APP_SECRET",
        "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    ) == ["META_WHATSAPP_APP_SECRET"]


def test_render_report_is_sanitized() -> None:
    report = smoke.render_report(
        [
            smoke.CheckResult(
                name="meta_signed_status_webhook",
                ok=True,
                status=200,
                latency_ms=1.23,
                summary={"accepted": True},
            )
        ]
    )

    assert "private-token" not in report
    assert "phone_e164" not in report
    assert "OTP codes" in report
    assert "passed: 1/1" in report
    assert "Meta outbox" in report
    assert "Meta OTP" in report
    assert "Meta inbound chat" in report


def test_meta_webhook_verification_smoke_uses_challenge(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request_text(method, url, headers=None):
        captured.update(method=method, url=url, headers=headers)
        return 200, "challenge-value", None

    monkeypatch.setattr(smoke, "request_text", fake_request_text)

    result = smoke.smoke_meta_webhook_verification(
        base_url="http://127.0.0.1:8000/",
        verify_token="token with spaces",
        challenge="challenge-value",
    )

    assert result.ok is True
    assert captured["method"] == "GET"
    assert "hub.verify_token=token+with+spaces" in captured["url"]
    assert "//integrations" not in captured["url"]


def test_meta_signed_status_webhook_smoke_posts_status_only(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request_json(method, url, headers=None, body=None):
        captured.update(method=method, url=url, headers=headers, body=body)
        return 200, {"status": "accepted"}, None

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.smoke_meta_signed_status_webhook(
        base_url="http://127.0.0.1:8000",
        app_secret="app-secret",
    )

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["headers"]["X-Hub-Signature-256"].startswith("sha256=")
    assert b"statuses" in captured["body"]
    assert b"messages" not in captured["body"]


def test_meta_chat_inbound_smoke_posts_signed_text_without_reporting_body(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request_json(method, url, headers=None, body=None):
        captured.update(method=method, url=url, headers=headers, body=body)
        return 200, {"status": "accepted"}, None

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.smoke_meta_chat_inbound_message(
        base_url="http://127.0.0.1:8000",
        app_secret="app-secret",
        from_wa_id="+5511999999999",
        text="Mensagem inbound segura",
    )
    report = smoke.render_report([result])

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["headers"]["X-Hub-Signature-256"].startswith("sha256=")
    assert b"messages" in captured["body"]
    assert b"Mensagem inbound segura" in captured["body"]
    assert "+5511999999999" not in report
    assert "Mensagem inbound segura" not in report


def test_hermes_otp_smoke_sends_whatsapp_chat_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request_json(method, url, headers=None, body=None):
        captured.update(method=method, url=url, headers=headers, body=body)
        return 200, {"status": "delivered"}, None

    monkeypatch.setattr(smoke, "request_json", fake_request_json)

    result = smoke.smoke_hermes_otp_delivery(
        base_url="https://hermes.example.test",
        webhook_secret="hermes-secret",
        path="/webhooks/supportfaq-otp",
        phone="+5541996565511",
    )

    payload = json.loads(captured["body"].decode("utf-8"))
    assert result.ok is True
    assert captured["url"] == "https://hermes.example.test/webhooks/supportfaq-otp"
    assert payload["phone_e164"] == "+5541996565511"
    assert payload["chat_id"] == "5541996565511@s.whatsapp.net"
    assert captured["headers"]["X-Webhook-Signature"].startswith("sha256=")


def test_main_refuses_without_target(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["meta_whatsapp_private_smoke.py"])

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "Choose at least one smoke target" in output.err
    assert "--meta-otp" in output.err


def test_direct_script_invocation_bootstraps_repo_imports() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/meta_whatsapp_private_smoke.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Choose at least one smoke target" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_meta_outbox_message_smoke_uses_dispatcher_without_printing_phone(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_deliver(event):
        captured.update(event)

    monkeypatch.setattr(smoke, "deliver", fake_deliver)

    result = smoke.smoke_meta_outbox_message_delivery(
        to="+5511999999999",
        text="Mensagem segura",
    )
    report = smoke.render_report([result])

    assert result.ok is True
    assert captured["event_type"] == "whatsapp.message.requested"
    assert captured["payload_sanitized"]["to"] == "+5511999999999"
    assert captured["payload_sanitized"]["text"] == "Mensagem segura"
    assert "+5511999999999" not in report
    assert "Mensagem segura" not in report


def test_meta_otp_smoke_uses_adapter_without_reporting_phone_or_code(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        def send_template(self, **kwargs) -> None:
            captured["send_template_kwargs"] = kwargs

    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("META_WHATSAPP_OTP_TEMPLATE_NAME", "web_login_otp")
    monkeypatch.setattr(smoke, "MetaWhatsAppClient", FakeClient)

    result = smoke.smoke_meta_otp_delivery(
        phone="+5511999999999",
        code="123456",
        expires_in_seconds=300,
    )
    report = smoke.render_report([result])

    assert result.ok is True
    assert captured["send_template_kwargs"]["to"] == "+5511999999999"
    assert captured["send_template_kwargs"]["template_name"] == "web_login_otp"
    assert captured["send_template_kwargs"]["components"][0]["parameters"][0]["text"] == "123456"
    assert "+5511999999999" not in report
    assert "123456" not in report
    assert "access-token" not in report


def test_meta_otp_smoke_sanitizes_delivery_errors(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        def send_template(self, **kwargs) -> None:
            raise RuntimeError("provider rejected token provider-private-marker +5511999999999")

    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("META_WHATSAPP_OTP_TEMPLATE_NAME", "web_login_otp")
    monkeypatch.setattr(smoke, "MetaWhatsAppClient", FakeClient)

    result = smoke.smoke_meta_otp_delivery(
        phone="+5511999999999",
        code="123456",
        expires_in_seconds=300,
    )

    assert result.ok is False
    assert result.error == "RuntimeError"


def test_meta_outbox_message_smoke_sanitizes_delivery_errors(monkeypatch) -> None:
    def fake_deliver(event):
        raise RuntimeError("provider rejected token provider-private-marker +5511999999999")

    monkeypatch.setattr(smoke, "deliver", fake_deliver)

    result = smoke.smoke_meta_outbox_message_delivery(
        to="+5511999999999",
        text="Mensagem segura",
    )

    assert result.ok is False
    assert result.error == "RuntimeError"


def test_main_requires_meta_outbox_to_with_meta_outbox_message(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-outbox-message"],
    )
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT", "meta_whatsapp")

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-outbox-to is required" in output.err


def test_main_requires_meta_outbox_to_before_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-outbox-message"],
    )
    monkeypatch.delenv("META_WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT", raising=False)

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-outbox-to is required" in output.err
    assert "Missing required env" not in output.err


def test_main_requires_meta_otp_phone_with_meta_otp(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-otp"],
    )
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("META_WHATSAPP_OTP_TEMPLATE_NAME", "web_login_otp")

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-otp-phone is required" in output.err


def test_main_requires_meta_otp_phone_before_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-otp"],
    )
    monkeypatch.delenv("META_WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("META_WHATSAPP_OTP_TEMPLATE_NAME", raising=False)

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-otp-phone is required" in output.err
    assert "Missing required env" not in output.err


def test_main_requires_hermes_phone_with_hermes_otp(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--hermes-otp"],
    )
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.example.test")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", "hermes-secret")

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--hermes-phone is required" in output.err


def test_main_requires_hermes_phone_before_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--hermes-otp"],
    )
    monkeypatch.delenv("HERMES_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_WEBHOOK_SECRET", raising=False)

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--hermes-phone is required" in output.err
    assert "Missing required env" not in output.err


def test_main_rejects_wrong_meta_outbox_transport(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "meta_whatsapp_private_smoke.py",
            "--meta-outbox-message",
            "--meta-outbox-to",
            "+5511999999999",
        ],
    )
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT", "internal_webhook")

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "must be meta_whatsapp" in output.err


def test_main_requires_meta_chat_from_with_meta_chat_inbound(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-chat-inbound"],
    )
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", "app-secret")

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-chat-from is required" in output.err


def test_main_requires_meta_chat_from_before_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["meta_whatsapp_private_smoke.py", "--meta-chat-inbound"],
    )
    monkeypatch.delenv("META_WHATSAPP_APP_SECRET", raising=False)

    code = smoke.main()
    output = capsys.readouterr()

    assert code == 2
    assert "--meta-chat-from is required" in output.err
    assert "Missing required env" not in output.err
