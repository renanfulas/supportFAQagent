import pytest
from fastapi.testclient import TestClient

from app.core.config import LOCAL_DEV_API_KEY, Settings, get_settings
from app.core.request_context import REQUEST_ID_HEADER
from app.main import app, create_app


API_KEY_HEADER = {"X-API-Key": LOCAL_DEV_API_KEY}
client = TestClient(app)


def test_api_secret_key_is_required_outside_development(monkeypatch) -> None:
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValueError, match="API_SECRET_KEY is required"):
        Settings(_env_file=None)


def test_api_secret_key_uses_local_default_only_in_development(monkeypatch) -> None:
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    assert Settings(_env_file=None).api_secret_key == LOCAL_DEV_API_KEY


def test_public_chat_ui_requires_secure_cookie_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    monkeypatch.setenv("WEB_CHAT_COOKIE_SECURE", "false")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")

    with pytest.raises(ValueError, match="WEB_CHAT_COOKIE_SECURE must be true"):
        Settings(_env_file=None)


def test_public_chat_ui_requires_rate_limit_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    monkeypatch.setenv("WEB_CHAT_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")

    with pytest.raises(ValueError, match="WEB_CHAT_RATE_LIMIT_PER_MINUTE must be at least 1"):
        Settings(_env_file=None)


def test_public_chat_ui_defaults_cookie_secure_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.delenv("WEB_CHAT_COOKIE_SECURE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.web_chat_cookie_secure is True


def test_web_whatsapp_auth_requires_identity_hash_secret(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "true")
    monkeypatch.delenv("IDENTITY_HASH_SECRET", raising=False)
    monkeypatch.setenv("OTP_DIGEST_SECRET", "otp-secret")

    with pytest.raises(ValueError, match="IDENTITY_HASH_SECRET is required"):
        Settings(_env_file=None)


def test_web_whatsapp_auth_requires_distinct_secrets(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "same-secret")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "same-secret")

    with pytest.raises(ValueError, match="must be different"):
        Settings(_env_file=None)


def test_handoff_consent_gate_requires_web_whatsapp_auth(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_HANDOFF_CONSENT_GATE", "true")
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "false")

    with pytest.raises(ValueError, match="ENABLE_HANDOFF_CONSENT_GATE requires"):
        Settings(_env_file=None)


def test_handoff_consent_gate_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_HANDOFF_CONSENT_GATE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.enable_handoff_consent_gate is False
    assert settings.otp_abandonment_reminder_minutes == 15


def test_chat_requires_api_key() -> None:
    response = client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "auth-chat-1"},
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-chat-1"
    assert response.json()["detail"] == "Invalid API key"


def test_chat_accepts_provider_key_when_chat_ui_is_enabled(
    monkeypatch,
) -> None:
    captured: dict[str, str | None] = {}

    class FakeWrapper:
        def __init__(
            self,
            provider: str,
            model: str,
            api_key: str | None = None,
        ) -> None:
            captured["api_key"] = api_key

        def generate_answer(self, prompt: str) -> str:
            return "Resposta com chave de teste."

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_CHAT_UI", "true")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)
    get_settings.cache_clear()
    staging_client = TestClient(create_app())

    response = staging_client.post(
        "/chat",
        headers={
            REQUEST_ID_HEADER: "chat-ui-provider-key",
            "X-LLM-API-Key": "sk-user-test",
        },
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("Resposta com chave de teste.")
    assert "temporariamente indisponivel" in response.json()["answer"]
    assert captured["api_key"] == "sk-user-test"
    get_settings.cache_clear()


def test_chat_alias_uses_environment_provider_key(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeWrapper:
        def __init__(
            self,
            provider: str,
            model: str,
            api_key: str | None = None,
        ) -> None:
            captured["api_key"] = api_key

        def generate_answer(self, prompt: str) -> str:
            return "Resposta com alias do projeto."

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_CHAT_UI", "true")
    monkeypatch.setenv("API_SECRET_KEY", "staging-test-secret")
    monkeypatch.setenv("PROJECT_LLM_API_KEY_ALIAS", "project-test-alias")
    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)
    get_settings.cache_clear()
    staging_client = TestClient(create_app())

    response = staging_client.post(
        "/chat",
        headers={
            REQUEST_ID_HEADER: "chat-ui-project-alias",
            "X-LLM-API-Key": "project-test-alias",
        },
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("Resposta com alias do projeto.")
    assert "temporariamente indisponivel" in response.json()["answer"]
    assert captured["api_key"] is None
    get_settings.cache_clear()


def test_chat_ui_provider_key_does_not_bypass_auth_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_CHAT_UI", "true")
    monkeypatch.setenv("API_SECRET_KEY", "production-test-secret")
    get_settings.cache_clear()
    production_client = TestClient(create_app())

    response = production_client.post(
        "/chat",
        headers={
            REQUEST_ID_HEADER: "chat-ui-production-blocked",
            "X-LLM-API-Key": "sk-user-test",
        },
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "chat-ui-production-blocked"
    assert response.json()["detail"] == "Invalid API key"
    get_settings.cache_clear()


def test_feedback_requires_api_key() -> None:
    response = client.post(
        "/feedback",
        headers={REQUEST_ID_HEADER: "auth-feedback-1"},
        json={
            "helpful": True,
            "source": "test",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-feedback-1"
    assert response.json()["detail"] == "Invalid API key"


def test_ingestion_preview_requires_api_key() -> None:
    response = client.post(
        "/ingestion/preview",
        headers={REQUEST_ID_HEADER: "auth-ingestion-1"},
        json={
            "domain": "suporte-vps-whatsapp",
            "documents": [
                {
                    "title": "Teste",
                    "content": "Conteudo valido.",
                }
            ],
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-ingestion-1"
    assert response.json()["detail"] == "Invalid API key"


def test_ingestion_domain_preview_requires_api_key() -> None:
    response = client.get(
        "/ingestion/suporte-vps-whatsapp/preview",
        headers={REQUEST_ID_HEADER: "auth-ingestion-domain-1"},
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-ingestion-domain-1"
    assert response.json()["detail"] == "Invalid API key"


def test_domains_requires_api_key() -> None:
    response = client.get(
        "/domains",
        headers={REQUEST_ID_HEADER: "auth-domains-1"},
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-domains-1"
    assert response.json()["detail"] == "Invalid API key"


def test_zoom_join_requires_api_key() -> None:
    response = client.post(
        "/zoom/join",
        headers={REQUEST_ID_HEADER: "auth-zoom-join-1"},
        json={
            "meeting_url": "https://zoom.us/j/123456789",
            "webhook_url": "https://example.test/zoom/webhook",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "auth-zoom-join-1"
    assert response.json()["detail"] == "Invalid API key"
