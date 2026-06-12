import json
from pathlib import Path

from scripts.mock_evolution_api import validate_send_text_request


WORKFLOW = Path("deploy/n8n/workflows/whatsapp-to-bot.json")


def test_evolution_mock_accepts_authenticated_send_text_contract() -> None:
    status, response = validate_send_text_request(
        path="/message/sendText/supportfaq",
        headers={"apikey": "private-key"},
        body=json.dumps(
            {"number": "5511000000000@s.whatsapp.net", "text": "Resposta segura."}
        ).encode(),
        expected_api_key="private-key",
    )

    assert status == 200
    assert response["status"] == "accepted"
    assert response["message_id"]


def test_evolution_mock_rejects_missing_auth_and_invalid_payload() -> None:
    unauthorized, _ = validate_send_text_request(
        path="/message/sendText/supportfaq",
        headers={},
        body=b'{"number":"safe","text":"safe"}',
        expected_api_key="private-key",
    )
    invalid_payload, response = validate_send_text_request(
        path="/message/sendText/supportfaq",
        headers={"apikey": "private-key"},
        body=b'{"number":"safe","text":""}',
        expected_api_key="private-key",
    )

    assert unauthorized == 401
    assert invalid_payload == 422
    assert response["status"] == "invalid_text"


def test_workflow_send_text_shape_matches_local_evolution_contract() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    workflow = json.loads(raw)
    names = {node["name"] for node in workflow["nodes"]}

    assert "Authenticated Evolution Webhook" in names
    assert "Send Answer Through Evolution" in names
    assert "/message/sendText/" in raw
    assert "number:" in raw
    assert "text:" in raw
    assert "authentication\": \"headerAuth\"" in raw
    assert "'evolution:' + $json.body.data.key.id" in raw
