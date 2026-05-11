from fastapi.testclient import TestClient

from app.core.request_context import REQUEST_ID_HEADER
from app.main import app


client = TestClient(app)


def test_post_ingestion_preview_chunks_payload_documents() -> None:
    response = client.post(
        "/ingestion/preview",
        headers={REQUEST_ID_HEADER: "ingest-123"},
        json={
            "domain": "suporte-vps-whatsapp",
            "chunk_size": 200,
            "documents": [
                {
                    "title": "Instalacao Evolution",
                    "source": "manual.md",
                    "content": "Valide Docker, portas, Traefik e logs antes de conectar o WhatsApp.",
                }
            ],
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["request_id"] == "ingest-123"
    assert payload["domain"] == "suporte-vps-whatsapp"
    assert payload["document_count"] == 1
    assert payload["chunk_count"] == 1
    assert payload["chunks"][0]["source"] == "manual.md"
    assert payload["chunks"][0]["title"] == "Instalacao Evolution"
    assert "Valide Docker" in payload["sample_chunks"][0]


def test_post_ingestion_preview_uses_payload_source_fallback() -> None:
    response = client.post(
        "/ingestion/preview",
        json={
            "domain": "suporte-vps-whatsapp",
            "documents": [
                {
                    "title": "QR Code",
                    "content": "Quando o QR Code falhar, gere nova sessao e revise logs.",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["chunks"][0]["source"] == "payload:1"


def test_post_ingestion_preview_rejects_blank_document_content() -> None:
    response = client.post(
        "/ingestion/preview",
        json={
            "domain": "suporte-vps-whatsapp",
            "documents": [
                {
                    "title": "QR Code",
                    "content": "   ",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["request_id"]


def test_post_ingestion_preview_returns_404_for_unknown_domain() -> None:
    response = client.post(
        "/ingestion/preview",
        headers={REQUEST_ID_HEADER: "ingest-404"},
        json={
            "domain": "nao-existe",
            "documents": [
                {
                    "title": "Teste",
                    "content": "Conteudo valido.",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert response.json()["request_id"] == "ingest-404"
