from app.api.schemas.chat import ChatResponse
from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse


def test_chat_response_contract_fields_remain_serializable() -> None:
    payload = ChatResponse(
        request_id="req-123",
        domain="suporte-vps-whatsapp",
        answer="Resposta segura.",
        confidence=0.82,
        escalated=True,
        handoff_reasons=["low_confidence", "out_of_scope"],
        references=[
            "domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md",
            "domains/suporte-vps-whatsapp/knowledge/faqs/ssh-timeout-vps.md",
        ],
        error_code="retrieval_error",
    ).model_dump()

    assert payload["request_id"] == "req-123"
    assert payload["domain"] == "suporte-vps-whatsapp"
    assert payload["escalated"] is True
    assert isinstance(payload["handoff_reasons"], list)
    assert all(isinstance(item, str) for item in payload["handoff_reasons"])
    assert isinstance(payload["references"], list)
    assert all(isinstance(item, str) for item in payload["references"])
    assert payload["error_code"] == "retrieval_error"


def test_feedback_request_contract_normalizes_optional_fields() -> None:
    payload = FeedbackRequest(
        request_id=" req-123 ",
        session_id=" session-xyz ",
        message_id=" ",
        helpful=False,
        reason=" needs_review ",
        comment=" comentario ",
        source=" n8n ",
        escalated=True,
        handoff_reasons=[" low_confidence ", " "],
        references=[
            " domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md ",
            " ",
        ],
        error_code=" provider_error ",
    ).model_dump()

    assert payload["request_id"] == "req-123"
    assert payload["session_id"] == "session-xyz"
    assert payload["message_id"] is None
    assert payload["reason"] == "needs_review"
    assert payload["comment"] == "comentario"
    assert payload["source"] == "n8n"
    assert payload["escalated"] is True
    assert payload["handoff_reasons"] == ["low_confidence"]
    assert payload["references"] == [
        "domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md"
    ]
    assert payload["error_code"] == "provider_error"


def test_feedback_response_contract_remains_simple_for_future_persistence() -> None:
    payload = FeedbackResponse(
        feedback_id="fb-123",
        accepted=True,
        status="accepted",
        storage="pending_persistence",
    ).model_dump()

    assert payload == {
        "feedback_id": "fb-123",
        "accepted": True,
        "status": "accepted",
        "storage": "pending_persistence",
    }
