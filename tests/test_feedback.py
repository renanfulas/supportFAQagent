from fastapi.testclient import TestClient

from app.main import app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}
client = TestClient(app)


def test_create_feedback_accepts_valid_payload() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "req-1",
            "session_id": "session-1",
            "helpful": True,
            "reason": "resolved",
            "comment": "A resposta ajudou.",
            "source": "test",
            "escalated": True,
            "handoff_reasons": ["low_confidence", "provider_error"],
            "references": ["domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md"],
            "error_code": "provider_error",
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["feedback_id"]
    assert payload["accepted"] is True
    assert payload["status"] == "accepted"
    assert payload["storage"] == "pending_persistence"


def test_create_feedback_requires_helpful_flag() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "req-1",
            "comment": "Sem helpful deve falhar.",
        },
    )

    assert response.status_code == 422


def test_create_feedback_normalizes_blank_optional_fields() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "   ",
            "session_id": " session-1 ",
            "helpful": False,
            "reason": "   ",
            "source": " n8n ",
            "handoff_reasons": [" low_confidence ", "   "],
            "references": [" domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md ", " "],
            "error_code": " provider_error ",
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_create_feedback_accepts_chat_context_fields() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "req-2",
            "helpful": False,
            "source": "n8n",
            "escalated": True,
            "handoff_reasons": ["low_confidence"],
            "references": [
                "domains/suporte-vps-whatsapp/knowledge/faqs/risco-bloqueio-whatsapp.md"
            ],
            "error_code": "provider_error",
        },
    )

    assert response.status_code == 200
    assert response.json()["storage"] == "pending_persistence"


def test_create_feedback_rejects_blank_source() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "helpful": True,
            "source": "   ",
        },
    )

    assert response.status_code == 422


def test_create_feedback_rejects_oversized_comment() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "helpful": True,
            "comment": "x" * 1001,
        },
    )

    assert response.status_code == 422


def test_create_feedback_rejects_too_many_handoff_reasons() -> None:
    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "helpful": True,
            "handoff_reasons": [f"reason-{index}" for index in range(11)],
        },
    )

    assert response.status_code == 422
