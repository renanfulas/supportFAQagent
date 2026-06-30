from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import chat, feedback
from app.core import chat_observability
from app.core.config import Settings, get_settings
from app.core.rate_limit import InMemoryRateLimiter
from app.core.request_context import REQUEST_ID_HEADER
from app.db.operational import ChatPersistenceResult
from app.domain_engine.models import DomainConfig
from app.integrations.hermes.chat_transport import HermesChatTransport
from app.integrations.hermes.client import HermesSendResult
from app.integrations.hermes.inbound import HermesInboundMessage
from app.main import create_app
from app.orchestration.domain_router import DomainRouter, RoutableDomain


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
    assert captured["error_code"] == "provider_error"
    assert captured["provider_failure_kind"] == "missing_credentials"
    assert captured["retrieval_backend"] == get_settings().retrieval_backend
    assert isinstance(captured["references_count"], int)
    assert captured["references_count"] >= 0
    assert isinstance(captured["total_ms"], float)
    assert isinstance(captured["retrieval_ms"], float)
    assert isinstance(captured["llm_ms"], float)
    assert captured["total_ms"] >= captured["retrieval_ms"]


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


class _FakeDomainLoader:
    def load(self, domain_name: str):
        return DomainConfig(
            name=domain_name, display_name=domain_name, root_path=Path(".")
        )


class _FakeChatService:
    def answer(self, **kwargs):
        return {
            "domain": "vendas",
            "answer": "Resposta de vendas.",
            "confidence": 0.8,
            "escalated": False,
            "handoff_reasons": [],
            "references": ["hostgator-hospedagem-de-sites.md"],
            "error_code": None,
            "observability": {"total_ms": 12.0, "retrieval_ms": 4.0, "llm_ms": 6.0},
        }


class _FakeRepository:
    def record_chat(self, audit):
        return ChatPersistenceResult(
            handoff_status="handoff_not_required",
            persistence_status="persisted",
            turn_id="turn-id",
        )


class _FakeClient:
    def send_text(self, *, to: str, text: str, message_id: str) -> HermesSendResult:
        return HermesSendResult(message_id="hermes-out")


def test_hermes_transport_emits_chat_completed_with_session_hash(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields):
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setattr(chat_observability, "log_event", capture_log_event)

    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(
        domains=(
            RoutableDomain(
                name="suporte-vps-whatsapp",
                display_name="Suporte VPS e WhatsApp",
                keywords=("vps", "ssh", "whatsapp"),
            ),
            RoutableDomain(
                name="vendas",
                display_name="Vendas HostGator",
                keywords=("hospedagem", "plano", "contratar"),
            ),
        ),
        default_domain="suporte-vps-whatsapp",
    )
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=_FakeClient(),
        domain_loader=_FakeDomainLoader(),
        chat_service=_FakeChatService(),
        repository=_FakeRepository(),
        router=router,
        rate_limiter=InMemoryRateLimiter(max_requests=1000),
    )

    transport.handle_text_message(
        message=HermesInboundMessage(
            message_id="h1",
            from_wa_id="5511999999999@s.whatsapp.net",
            chat_id="5511999999999@s.whatsapp.net",
            text="quero contratar um plano de hospedagem",
        ),
        request_id="r1",
    )

    assert captured["event"] == "chat_completed"
    assert captured["channel"] == "whatsapp"
    assert captured["domain"] == "vendas"
    assert "session_id" not in captured
    assert "5511999999999" not in str(captured["session_id_hash"])
    assert captured["handoff_status"] == "handoff_not_required"
    assert captured["persistence_status"] == "persisted"
    assert captured["request_id_reused"] is False
    assert captured["retrieval_backend"] == settings.retrieval_backend
    assert captured["references_count"] == 1
    assert captured["total_ms"] == 12.0
    assert captured["retrieval_ms"] == 4.0
    assert captured["llm_ms"] == 6.0


def test_hermes_menu_turn_does_not_emit_chat_completed(monkeypatch) -> None:
    events: list[str] = []

    def capture_log_event(_logger, event: str, **fields):
        events.append(event)

    monkeypatch.setattr(chat_observability, "log_event", capture_log_event)

    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(
        domains=(
            RoutableDomain(
                name="suporte-vps-whatsapp",
                display_name="Suporte VPS e WhatsApp",
                keywords=("vps", "ssh", "whatsapp"),
            ),
            RoutableDomain(
                name="vendas",
                display_name="Vendas HostGator",
                keywords=("hospedagem", "plano", "contratar"),
            ),
        ),
        default_domain="suporte-vps-whatsapp",
    )
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=_FakeClient(),
        domain_loader=_FakeDomainLoader(),
        chat_service=_FakeChatService(),
        repository=_FakeRepository(),
        router=router,
        rate_limiter=InMemoryRateLimiter(max_requests=1000),
    )

    # A greeting that only shows the menu never calls answer, so no chat_completed.
    transport.handle_text_message(
        message=HermesInboundMessage(
            message_id="h1",
            from_wa_id="5511999999999@s.whatsapp.net",
            chat_id="5511999999999@s.whatsapp.net",
            text="Oi",
        ),
        request_id="r1",
    )

    assert "chat_completed" not in events


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
