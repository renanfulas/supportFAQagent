import logging

from fastapi import APIRouter, Request

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.feedback.service import FeedbackService


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=FeedbackResponse)
def create_feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
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
        storage=response.storage,
    )
    return response
