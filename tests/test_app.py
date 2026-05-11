from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_app_import_and_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_domains_returns_known_domain() -> None:
    response = client.get("/domains")

    assert response.status_code == 200
    assert "suporte-vps-whatsapp" in response.json()["domains"]


def test_ingestion_preview_returns_documents_and_chunks() -> None:
    response = client.get("/ingestion/suporte-vps-whatsapp/preview")

    assert response.status_code == 200

    payload = response.json()
    assert payload["domain"] == "suporte-vps-whatsapp"
    assert payload["document_count"] >= 1
    assert payload["chunk_count"] >= payload["document_count"]
    assert payload["sample_chunks"]


def test_chat_returns_mock_answer_with_references() -> None:
    response = client.post(
        "/chat",
        json={
            "domain": "suporte-vps-whatsapp",
            "session_id": "session-1",
            "message": "Como instalar a Evolution API no VPS?",
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["domain"] == "suporte-vps-whatsapp"
    assert "mock provider" in payload["answer"].lower()
    assert isinstance(payload["confidence"], float)
    assert isinstance(payload["escalated"], bool)
    assert payload["references"]


def test_chat_returns_404_for_unknown_domain() -> None:
    response = client.post(
        "/chat",
        json={
            "domain": "nao-existe",
            "message": "teste",
        },
    )

    assert response.status_code == 404
