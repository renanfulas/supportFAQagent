from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
import pytest

from app.core.config import get_settings
from app.integrations.webhook_ingress import (
    CLAIMED,
    DUPLICATE,
    IN_PROGRESS,
    PAYLOAD_CONFLICT,
    ClaimResult,
    verify_signature,
)
from app.main import create_app


SECRET = "ingress-test-secret"
EVENT_PATH = "/internal/webhooks/outbox/handoff.requested"


def signed_headers(body: bytes, *, key: str = "handoff:req-1") -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Idempotency-Key": key,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"sha256={signature}",
    }


@pytest.fixture
def ingress_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ENABLE_OUTBOX_INGRESS", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("OUTBOX_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("VERIFIED_HANDOFF_WEBHOOK_URL", "https://delivery.internal/handoff")
    monkeypatch.setattr("app.db.runtime.DatabaseRuntime.open", lambda self: None)
    get_settings.cache_clear()
    client = TestClient(create_app())
    yield client
    get_settings.cache_clear()


def test_signature_rejects_missing_secret_and_old_timestamp() -> None:
    body = b'{"safe":"payload"}'
    headers = signed_headers(body)
    sent_at = int(headers["X-Webhook-Timestamp"])

    assert verify_signature(
        body=body,
        timestamp=headers["X-Webhook-Timestamp"],
        signature=headers["X-Webhook-Signature"],
        secret=SECRET,
        now=sent_at + 1,
    )
    assert not verify_signature(
        body=body,
        timestamp=headers["X-Webhook-Timestamp"],
        signature=headers["X-Webhook-Signature"],
        secret=SECRET,
        now=sent_at + 400,
    )


@pytest.mark.parametrize(
    ("claim_status", "expected_status", "expected_body"),
    [
        (DUPLICATE, 200, "duplicate"),
        (IN_PROGRESS, 425, "delivery_in_progress"),
        (PAYLOAD_CONFLICT, 409, "idempotency_payload_conflict"),
    ],
)
def test_ingress_handles_idempotency_states(
    monkeypatch: pytest.MonkeyPatch,
    ingress_client: TestClient,
    claim_status: str,
    expected_status: int,
    expected_body: str,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.claim",
        lambda *args, **kwargs: ClaimResult(claim_status, 1),
    )
    body = json.dumps({"summary": "safe"}, separators=(",", ":")).encode()

    response = ingress_client.post(EVENT_PATH, content=body, headers=signed_headers(body))

    assert response.status_code == expected_status
    assert expected_body in response.text


def test_ingress_forwards_claimed_payload_and_marks_delivered(
    monkeypatch: pytest.MonkeyPatch,
    ingress_client: TestClient,
) -> None:
    delivered: list[str] = []
    forwarded: dict[str, object] = {}

    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.claim",
        lambda *args, **kwargs: ClaimResult(CLAIMED, 1),
    )
    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.mark_delivered",
        lambda self, key: delivered.append(key),
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, *, json, headers, timeout):
        forwarded.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.api.routes.internal_webhooks.requests.post", fake_post)
    body = b'{"summary":"safe"}'

    response = ingress_client.post(EVENT_PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert response.json()["status"] == "delivered"
    assert delivered == ["handoff:req-1"]
    assert forwarded["url"] == "https://delivery.internal/handoff"
    assert forwarded["json"] == {"summary": "safe"}
    assert "X-Webhook-Signature" not in forwarded["headers"]


def test_ingress_rejects_invalid_signature_before_claim(
    monkeypatch: pytest.MonkeyPatch,
    ingress_client: TestClient,
) -> None:
    claimed = False

    def claim(*args, **kwargs):
        nonlocal claimed
        claimed = True
        return ClaimResult(CLAIMED, 1)

    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.claim",
        claim,
    )
    body = b'{"summary":"safe"}'
    headers = signed_headers(body)
    headers["X-Webhook-Signature"] = "sha256=invalid"

    response = ingress_client.post(EVENT_PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert claimed is False


def test_ingress_marks_retryable_failure_when_verified_webhook_fails(
    monkeypatch: pytest.MonkeyPatch,
    ingress_client: TestClient,
) -> None:
    failed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.claim",
        lambda *args, **kwargs: ClaimResult(CLAIMED, 1),
    )
    monkeypatch.setattr(
        "app.api.routes.internal_webhooks.WebhookIngressRepository.mark_failed",
        lambda self, key, error: failed.append((key, error)),
    )

    def fail_post(*args, **kwargs):
        import requests

        raise requests.Timeout("private detail")

    monkeypatch.setattr("app.api.routes.internal_webhooks.requests.post", fail_post)
    body = b'{"summary":"safe"}'

    response = ingress_client.post(EVENT_PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 502
    assert response.json()["detail"] == "verified_webhook_delivery_failed"
    assert "private detail" not in response.text
    assert failed == [("handoff:req-1", "verified_webhook_delivery_failed")]
