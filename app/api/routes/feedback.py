import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.core.config import get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import verify_api_key
from app.feedback.service import FeedbackService
from app.core.errors import DatabaseUnavailableError
from app.db.operational import FeedbackIntegrityConflictError


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=FeedbackResponse)
def create_feedback(
    payload: FeedbackRequest,
    request: Request,
    _: str = Depends(verify_api_key),
) -> FeedbackResponse:
    settings = get_settings()
    try:
        response = FeedbackService(request.app.state.database_runtime).record(payload)
    except FeedbackIntegrityConflictError as exc:
        raise HTTPException(status_code=409, detail="feedback_idempotency_conflict") from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="feedback_storage_unavailable") from exc
    log_event(
        logger,
        "feedback_recorded",
        request_id=get_request_id(request),
        chat_request_id=payload.request_id,
        session_id_hash=hash_sensitive_value(
            payload.session_id,
            secret=settings.persistence_hash_secret,
        ),
        helpful=payload.helpful,
        reason_present=payload.reason is not None,
        comment_present=payload.comment is not None,
        source=payload.source,
        escalated=payload.escalated,
        handoff_reason_count=len(payload.handoff_reasons),
        reference_count=len(payload.references),
        error_code_present=payload.error_code is not None,
        storage=response.storage,
        context_status=response.status,
    )
    return response
