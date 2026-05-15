import logging

from fastapi import APIRouter, Depends, Request

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import verify_api_key
from app.feedback.service import FeedbackService


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=FeedbackResponse)
def create_feedback(
    payload: FeedbackRequest,
    request: Request,
    _: str = Depends(verify_api_key),
) -> FeedbackResponse:
    response = FeedbackService().record(payload)
    log_event(
        logger,
        "feedback_recorded",
        request_id=get_request_id(request),
        chat_request_id=payload.request_id,
        session_id_hash=hash_sensitive_value(payload.session_id),
        helpful=payload.helpful,
        reason=payload.reason,
        source=payload.source,
        escalated=payload.escalated,
        handoff_reasons=payload.handoff_reasons,
        reference_count=len(payload.references),
        error_code=payload.error_code,
        storage=response.storage,
    )
    return response
