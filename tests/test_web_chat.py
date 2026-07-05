import pytest
from fastapi.testclient import TestClient

from app.api.schemas.feedback import FeedbackResponse
from app.core.config import get_settings
from app.core.request_context import REQUEST_ID_HEADER
from app.main import CHAT_STATIC_DIR, create_app


@pytest.fixture
def web_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        yield client
    finally:
        get_settings.cache_clear()


def test_web_chat_accepts_valid_payload_without_api_key_and_returns_public_contract(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: dict[str, object] = {}

    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        captured["domain"] = domain.name
        captured["question"] = question
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["provider_api_key"] = provider_api_key
        captured["channel"] = channel
        return {
            "request_id": request_id or "",
            "domain": domain.name,
            "answer": "Resposta publica segura.",
            "confidence": 0.91,
            "escalated": False,
            "handoff_reasons": [],
            "references": ["qrcode-whatsapp.md"],
            "error_code": None,
        }

    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-ok-1"},
        json={"message": "Como conectar o WhatsApp na Evolution API?"},
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-ok-1"
    assert "sfaq_web_session=" in response.headers["set-cookie"]

    payload = response.json()
    assert payload == {
        "request_id": "web-chat-ok-1",
        "answer": "Resposta publica segura.",
        "escalated": False,
        "handoff_reasons": [],
        "references": ["qrcode-whatsapp.md"],
        "support_code": "web-chat-ok-1",
        "error_code": None,
        "support_deep_link": None,
    }
    assert "domain" not in payload
    assert "confidence" not in payload
    assert captured["question"] == "Como conectar o WhatsApp na Evolution API?"
    assert isinstance(captured["session_id"], str)
    assert str(captured["session_id"]).startswith("web:")
    assert captured["provider_api_key"] is None
    assert captured["channel"] == "web"


def test_web_chat_rejects_domain_extra_field(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-domain-extra"},
        json={
            "message": "Como instalar Evolution API?",
            "domain": "suporte-vps-whatsapp",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-domain-extra"
    assert response.json()["request_id"] == "web-chat-domain-extra"


def test_web_chat_rejects_session_id_extra_field(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-session-extra"},
        json={
            "message": "Como instalar Evolution API?",
            "session_id": "web:forged",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-session-extra"
    assert response.json()["request_id"] == "web-chat-session-extra"


def test_web_chat_reuses_valid_anonymous_session_cookie(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: list[str | None] = []

    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        _ = (domain, question, provider_api_key, channel)
        captured.append(session_id)
        return {
            "request_id": request_id or "",
            "domain": "suporte-vps-whatsapp",
            "answer": "ok",
            "confidence": 0.5,
            "escalated": False,
            "handoff_reasons": [],
            "references": [],
            "error_code": None,
        }

    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    existing_session = "web:123e4567-e89b-12d3-a456-426614174000"
    web_client.cookies.set("sfaq_web_session", existing_session)

    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-cookie-reuse"},
        json={"message": "Teste de sessao."},
    )

    assert response.status_code == 200
    assert captured == [existing_session]
    assert "set-cookie" not in response.headers


def test_web_chat_rate_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        _ = (domain, question, session_id, provider_api_key, channel)
        return {
            "request_id": request_id or "",
            "domain": "suporte-vps-whatsapp",
            "answer": "ok",
            "confidence": 0.5,
            "escalated": False,
            "handoff_reasons": [],
            "references": [],
            "error_code": None,
        }

    monkeypatch.setenv("WEB_CHAT_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    get_settings.cache_clear()
    client = TestClient(create_app())
    payload = {"message": "Como instalar a Evolution API no VPS?"}

    first = client.post("/web/chat", json=payload)
    second = client.post("/web/chat", json=payload)
    third = client.post("/web/chat", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"]
    assert third.json()["detail"] == "Too many requests"
    assert third.json()["request_id"]
    get_settings.cache_clear()


def test_web_feedback_accepts_without_api_key_and_forces_source_web(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: dict[str, object] = {}

    def fake_record(self, payload) -> FeedbackResponse:
        captured["payload"] = payload.model_dump()
        return FeedbackResponse(
            feedback_id="feedback-web-1",
            accepted=True,
            status="accepted",
            storage="pending_persistence",
        )

    monkeypatch.setattr("app.feedback.service.FeedbackService.record", fake_record)

    session_id = "web:123e4567-e89b-12d3-a456-426614174001"
    web_client.cookies.set("sfaq_web_session", session_id)
    response = web_client.post(
        "/web/feedback",
        headers={REQUEST_ID_HEADER: "web-feedback-ok-1"},
        json={
            "request_id": "chat-request-1",
            "helpful": True,
            "reason": "resolved",
            "comment": "A resposta ajudou.",
        },
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "web-feedback-ok-1"
    assert response.json() == {
        "feedback_id": "feedback-web-1",
        "accepted": True,
        "status": "accepted",
        "storage": "pending_persistence",
    }
    assert captured["payload"] == {
        "request_id": "chat-request-1",
        "session_id": session_id,
        "message_id": None,
        "helpful": True,
        "reason": "resolved",
        "comment": "A resposta ajudou.",
        "source": "web",
        "escalated": None,
        "handoff_reasons": [],
        "references": [],
        "error_code": None,
    }


def test_web_feedback_rejects_extra_fields(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/feedback",
        headers={REQUEST_ID_HEADER: "web-feedback-extra"},
        json={
            "request_id": "chat-request-1",
            "helpful": False,
            "comment": "Nao ajudou.",
            "source": "browser-forged",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-feedback-extra"
    assert response.json()["request_id"] == "web-feedback-extra"


def test_chat_route_remains_protected_without_api_key(web_client: TestClient) -> None:
    response = web_client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "web-chat-does-not-open-chat"},
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-does-not-open-chat"
    assert response.json()["detail"] == "Invalid API key"


def test_public_chat_assets_do_not_contain_secret_strings() -> None:
    forbidden_strings = [
        "X-API-Key",
        "OPENAI_API_KEY",
        "API_SECRET_KEY",
        "X-LLM-API-Key",
    ]

    asset_files = sorted(path for path in CHAT_STATIC_DIR.glob("*") if path.is_file())

    assert asset_files

    for asset_file in asset_files:
        content = asset_file.read_text(encoding="utf-8")
        for forbidden in forbidden_strings:
            assert forbidden not in content, f"{forbidden} found in {asset_file.name}"
