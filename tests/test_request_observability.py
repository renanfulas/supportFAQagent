from fastapi.testclient import TestClient

from app.core.request_context import REQUEST_ID_HEADER
from app.main import app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}
client = TestClient(app)


def test_response_includes_generated_request_id_header() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]


def test_chat_reuses_inbound_request_id() -> None:
    response = client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "trace-123", **API_KEY_HEADER},
        json={
            "domain": "suporte-vps-whatsapp",
            "session_id": "session-1",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "trace-123"
    assert response.json()["request_id"] == "trace-123"


def test_unknown_domain_error_includes_request_id() -> None:
    response = client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "trace-404", **API_KEY_HEADER},
        json={
            "domain": "nao-existe",
            "message": "teste",
        },
    )

    assert response.status_code == 404
    assert response.headers[REQUEST_ID_HEADER] == "trace-404"
    assert response.json()["request_id"] == "trace-404"
    assert response.json()["detail"] == "Domain not found"


def test_validation_error_includes_request_id() -> None:
    response = client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "trace-422", **API_KEY_HEADER},
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "   ",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "trace-422"
    assert response.json()["request_id"] == "trace-422"


def test_oversized_inbound_request_id_is_replaced() -> None:
    response = client.get(
        "/health",
        headers={REQUEST_ID_HEADER: "x" * 81},
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] != "x" * 81
    assert response.headers[REQUEST_ID_HEADER]


def test_sensitive_or_free_text_request_id_is_replaced() -> None:
    for unsafe in ("sk-example-secret", "email=user@example.com", "texto livre"):
        response = client.get("/health", headers={REQUEST_ID_HEADER: unsafe})

        assert response.status_code == 200
        assert response.headers[REQUEST_ID_HEADER] != unsafe
