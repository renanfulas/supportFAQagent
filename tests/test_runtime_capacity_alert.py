from __future__ import annotations

import json

from scripts import check_runtime_capacity as capacity
from scripts import send_runtime_capacity_alert as alert


def test_parse_recipients_builds_whatsapp_chat_ids() -> None:
    targets = alert.parse_recipients("+55 11 937350535, +55 41 9806-0000")

    assert [target.phone_e164 for target in targets] == [
        "+5511937350535",
        "+554198060000",
    ]
    assert [target.chat_id for target in targets] == [
        "5511937350535@s.whatsapp.net",
        "554198060000@s.whatsapp.net",
    ]


def test_should_alert_defaults_to_critical_only() -> None:
    assert alert.should_alert("warning", "critical") is False
    assert alert.should_alert("critical", "critical") is True
    assert alert.should_alert("warning", "warning") is True


def test_alert_message_uses_sanitized_capacity_summary() -> None:
    message = alert.build_alert_message(
        status="critical",
        checks=[
            capacity.Check(
                "disk_capacity",
                "critical",
                "used_percent=90.0 free_gb=1.0 path=/",
                True,
            )
        ],
        force_test=False,
    )

    assert "supportFAQ capacity alert" in message
    assert "used_percent=90.0" in message
    assert "free_gb=1.0" in message
    assert "DATABASE_URL" not in message


def test_deliver_alert_posts_signed_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def getcode(self):
            return self.status

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(alert.request, "urlopen", fake_urlopen)

    result = alert.deliver_alert(
        base_url="https://hermes.example.test",
        webhook_secret="secret",
        delivery_path="/webhooks/supportfaq-alerts",
        timeout_seconds=3,
        target=alert.AlertTarget(
            phone_e164="+5511937350535",
            chat_id="5511937350535@s.whatsapp.net",
        ),
        message="supportFAQ capacity alert TEST",
        delivery_id="delivery-1",
    )

    payload = json.loads(captured["body"].decode("utf-8"))
    assert result.ok is True
    assert captured["url"] == "https://hermes.example.test/webhooks/supportfaq-alerts"
    assert payload["template"] == "runtime_capacity_alert"
    assert payload["chat_id"] == "5511937350535@s.whatsapp.net"
    assert payload["variables"]["message"] == "supportFAQ capacity alert TEST"
    assert not captured["headers"]["X-webhook-signature"].startswith("sha256=")


def test_report_does_not_print_phone_numbers_or_payload() -> None:
    report = alert.render_report(
        status="test",
        sent=True,
        checks=[
            capacity.Check(
                "disk_capacity",
                "ok",
                "used_percent=50.0 free_gb=10.0 path=/",
                False,
            )
        ],
        results=[alert.DeliveryResult(target_index=1, ok=True, status=200)],
    )

    assert "+5511937350535" not in report
    assert "5511937350535@s.whatsapp.net" not in report
    assert "raw payloads" in report
    assert "delivered: 1/1" in report
