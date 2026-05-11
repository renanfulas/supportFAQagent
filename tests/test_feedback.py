from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_feedback_accepts_valid_payload() -> None:
    response = client.post(
        "/feedback",
        json={
            "request_id": "req-1",
            "session_id": "session-1",
            "helpful": True,
            "reason": "resolved",
            "comment": "A resposta ajudou.",
            "source": "test",
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
        json={
            "request_id": "req-1",
            "comment": "Sem helpful deve falhar.",
        },
    )

    assert response.status_code == 422
