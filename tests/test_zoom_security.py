from fastapi.testclient import TestClient

from app.api.routes import zoom
from app.core.config import LOCAL_DEV_API_KEY, get_settings
from app.main import create_app


API_KEY_HEADER = {"X-API-Key": LOCAL_DEV_API_KEY}


def test_zoom_webhook_requires_secret_or_api_key(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET", "zoom-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/zoom/webhook",
        json={"event": "unknown_event"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid webhook secret"
    get_settings.cache_clear()


def test_zoom_webhook_accepts_configured_query_token(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET", "zoom-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/zoom/webhook?token=zoom-secret",
        json={"event": "unknown_event"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "received"}
    get_settings.cache_clear()


def test_zoom_join_appends_webhook_token_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id": "bot-123"}

    def fake_post(url: str, json: dict, headers: dict) -> FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setenv("RECALL_API_KEY", "recall-secret")
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET", "zoom-secret")
    monkeypatch.setattr(zoom.requests, "post", fake_post)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/zoom/join",
        headers={"X-API-Key": "staging-test-secret"},
        json={
            "meeting_url": "https://zoom.us/j/123456789",
            "webhook_url": "https://example.test/zoom/webhook",
        },
    )

    assert response.status_code == 200
    assert captured["url"] == "https://us-west-2.recall.ai/api/v1/bot"
    realtime_endpoint = captured["json"]["recording_config"]["realtime_endpoints"][0]
    assert realtime_endpoint["url"] == "https://example.test/zoom/webhook?token=zoom-secret"
    get_settings.cache_clear()


def test_zoom_webhook_logs_hashes_without_raw_payload(monkeypatch) -> None:
    events: list[dict[str, object]] = []

    def capture_log_event(_logger, event: str, **fields):
        events.append({"event": event, **fields})

    def fake_process_and_reply(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(zoom, "log_event", capture_log_event)
    monkeypatch.setattr(zoom, "process_and_reply", fake_process_and_reply)
    client = TestClient(create_app())

    payload = {
        "event": "participant_events.chat_message",
        "data": {
            "data": {
                "data": {"text": "@bot preciso de ajuda"},
                "participant": {"name": "Renan"},
            },
            "bot": {"id": "bot-xyz"},
            "domain": "suporte-vps-whatsapp",
        },
    }

    response = client.post(
        "/zoom/webhook",
        headers=API_KEY_HEADER,
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "processing"}
    queued_event = next(item for item in events if item["event"] == "zoom_webhook_chat_queued")
    assert queued_event["sender_hash"] != "Renan"
    assert queued_event["bot_id_hash"] != "bot-xyz"
    assert "payload" not in queued_event
    assert "chat_text" not in queued_event


def test_zoom_join_logs_meeting_url_hash(monkeypatch) -> None:
    events: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id": "bot-123"}

    def fake_post(url: str, json: dict, headers: dict) -> FakeResponse:
        return FakeResponse()

    def capture_log_event(_logger, event: str, **fields):
        events.append({"event": event, **fields})

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setenv("RECALL_API_KEY", "recall-secret")
    monkeypatch.setattr(zoom.requests, "post", fake_post)
    monkeypatch.setattr(zoom, "log_event", capture_log_event)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/zoom/join",
        headers={"X-API-Key": "staging-test-secret"},
        json={
            "meeting_url": "https://zoom.us/j/123456789",
            "webhook_url": "https://example.test/zoom/webhook",
        },
    )

    assert response.status_code == 200
    join_event = next(item for item in events if item["event"] == "zoom_join_requested")
    assert "meeting_url" not in join_event
    assert join_event["meeting_url_hash"] != "https://zoom.us/j/123456789"
    get_settings.cache_clear()
