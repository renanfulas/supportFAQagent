import json
from pathlib import Path

import pytest

from scripts.mock_outbox_webhook import verify_signature


WORKFLOWS = Path("deploy/n8n/workflows")


@pytest.mark.parametrize(
    "filename",
    ["whatsapp-to-bot.json", "escalation-notify.json", "web-otp-delivery.json"],
)
def test_workflow_templates_are_disabled_and_contain_no_credentials(filename: str) -> None:
    raw = (WORKFLOWS / filename).read_text(encoding="utf-8")
    workflow = json.loads(raw)

    assert workflow["active"] is False
    assert workflow["nodes"]
    assert "credentials" not in raw
    assert "sk-" not in raw
    assert "apiKey" not in raw


def test_internal_workflow_templates_require_verified_ingress_names() -> None:
    escalation = json.loads((WORKFLOWS / "escalation-notify.json").read_text())
    otp = json.loads((WORKFLOWS / "web-otp-delivery.json").read_text())

    assert escalation["nodes"][0]["name"] == "Verified Handoff Webhook"
    assert otp["nodes"][0]["name"] == "Verified OTP Webhook"


def test_whatsapp_workflow_calls_chat_and_sends_answer_back() -> None:
    workflow = json.loads((WORKFLOWS / "whatsapp-to-bot.json").read_text())
    names = {node["name"] for node in workflow["nodes"]}

    assert "Call supportFAQagent Chat" in names
    assert "Send Answer Through Evolution" in names
    assert workflow["connections"]["Call supportFAQagent Chat"]["main"][0][0]["node"] == (
        "Send Answer Through Evolution"
    )


def test_internal_workflow_runbook_requires_signed_ingress_before_activation() -> None:
    runbook = Path("docs/runbooks/n8n-versioned-workflows.md").read_text(
        encoding="utf-8"
    )

    assert "active: false" in runbook
    assert "X-Webhook-Signature" in runbook
    assert "HANDOFF_WEBHOOK_URL=http://supportfaq_api:8000/internal/webhooks/outbox/handoff.requested" in runbook
    assert "N8N_VERIFIED_HANDOFF_URL" in runbook


def test_signature_verifier_rejects_replay_window_and_invalid_signature() -> None:
    body = b'{"request_id":"req-1"}'
    secret = "dedicated-secret"
    timestamp = "1000"
    import hashlib
    import hmac

    signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    assert verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret=secret,
        now=1001,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret=secret,
        now=1400,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature="sha256=invalid",
        secret=secret,
        now=1001,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret="",
        now=1001,
    )
