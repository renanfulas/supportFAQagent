from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}


def test_chat_rate_limit_returns_429_with_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    client = TestClient(create_app())

    payload = {
        "domain": "suporte-vps-whatsapp",
        "message": "Como instalar a Evolution API no VPS?",
    }

    first = client.post("/chat", headers=API_KEY_HEADER, json=payload)
    second = client.post("/chat", headers=API_KEY_HEADER, json=payload)
    third = client.post("/chat", headers=API_KEY_HEADER, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"]
    assert third.json()["detail"] == "Too many requests"
    assert third.json()["request_id"]

    get_settings.cache_clear()


def test_rate_limit_applies_only_to_chat(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()
    client = TestClient(create_app())

    first_health = client.get("/health")
    second_health = client.get("/health")

    assert first_health.status_code == 200
    assert second_health.status_code == 200

    get_settings.cache_clear()
