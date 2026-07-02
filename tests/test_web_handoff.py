import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_handoff_consent_hidden_when_gate_disabled() -> None:
    response = TestClient(create_app()).post(
        "/web/handoff/consent", json={"request_id": "req-1"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_handoff_consent_requires_otp_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "true")
    monkeypatch.setenv("ENABLE_HANDOFF_CONSENT_GATE", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "identity-secret")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "otp-secret")
    client = TestClient(create_app())

    response = client.post("/web/handoff/consent", json={"request_id": "req-1"})

    assert response.status_code == 401
    assert response.json()["detail"] == "otp_confirmation_required"


def test_handoff_consent_rejects_extra_fields(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "true")
    monkeypatch.setenv("ENABLE_HANDOFF_CONSENT_GATE", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "identity-secret")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "otp-secret")
    client = TestClient(create_app())

    response = client.post(
        "/web/handoff/consent",
        json={"request_id": "req-1", "customer_id": "should-not-be-public"},
    )

    assert response.status_code == 422
