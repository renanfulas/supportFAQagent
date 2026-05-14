from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import chat, feedback
from app.core.request_context import REQUEST_ID_HEADER
from app.main import create_app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}


def test_chat_log_uses_session_id_hash(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields):
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setattr(chat, "log_event", capture_log_event)

    client = TestClient(create_app())
    response = client.post(
        "/chat",
        headers=API_KEY_HEADER,
        json={
            "domain": "suporte-vps-whatsapp",
            "session_id": "whatsapp:+5511999999999",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 200
    assert captured["event"] == "chat_completed"
    assert "session_id" not in captured
    assert captured["session_id_hash"] != "whatsapp:+5511999999999"


def test_feedback_log_uses_session_id_hash(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields):
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setattr(feedback, "log_event", capture_log_event)

    client = TestClient(create_app())
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "chat-1",
            "session_id": "whatsapp:+5511999999999",
            "helpful": True,
        },
    )

    assert response.status_code == 200
    assert captured["event"] == "feedback_recorded"
    assert "session_id" not in captured
    assert captured["session_id_hash"] != "whatsapp:+5511999999999"


def test_unexpected_error_returns_request_id_header() -> None:
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    hardened_app = create_app()
    hardened_app.router.routes.extend(app.router.routes)
    client = TestClient(hardened_app, raise_server_exceptions=False)

    response = client.get("/boom", headers={REQUEST_ID_HEADER: "trace-500"})

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "trace-500"
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": "trace-500",
    }
