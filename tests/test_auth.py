from fastapi.testclient import TestClient

from app.core.request_context import REQUEST_ID_HEADER
from app.main import app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}
client = TestClient(app)


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
