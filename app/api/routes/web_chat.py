import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.api.schemas.web_chat import (
    WebChatRequest,
    WebChatResponse,
    WebFeedbackRequest,
)
from app.core.config import get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.web_session import (
    get_or_create_public_session_id,
    set_public_session_cookie,
)
from app.domain_engine.loader import DomainLoader
from app.conversations.service import ConversationHistoryService
from app.feedback.service import FeedbackService
from app.orchestration.chat_flow import ChatFlowService
from app.core.errors import DatabaseUnavailableError
from app.db.operational import (
    ChatAuditInput,
    FeedbackIntegrityConflictError,
    HANDOFF_UNAVAILABLE,
    OperationalRepository,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=WebChatResponse)
def create_web_chat(
    payload: WebChatRequest,
    request: Request,
    response: Response,
) -> WebChatResponse:
    request_id = get_request_id(request)
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    domain = _load_default_domain(settings)

    database_runtime = request.app.state.database_runtime
    chat_response = ChatFlowService(
        history_service=ConversationHistoryService(database_runtime),
    ).answer(
        domain=domain,
        question=payload.message,
        session_id=session_id,
        request_id=request_id,
        provider_api_key=None,
        channel="web",
    )
    persistence_result = OperationalRepository(database_runtime).record_chat(
        ChatAuditInput(
            request_id=request_id,
            domain=str(chat_response["domain"]),
            session_id=session_id,
            question=payload.message,
            answer=str(chat_response["answer"]),
            confidence=float(chat_response["confidence"]),
            escalated=bool(chat_response["escalated"]),
            handoff_reasons=list(chat_response["handoff_reasons"]),
            references=list(chat_response["references"]),
            error_code=chat_response["error_code"],
            channel="web",
        )
    )
    chat_response["handoff_status"] = persistence_result.handoff_status
    chat_response["persistence_status"] = persistence_result.persistence_status
    if chat_response["handoff_status"] == HANDOFF_UNAVAILABLE:
        chat_response["answer"] = (
            f"{chat_response['answer']} O atendimento humano esta temporariamente indisponivel; "
            "guarde o codigo de suporte."
        )
    _log_web_chat_event(
        request_id=request_id,
        session_id=session_id,
        chat_response=chat_response,
        request_id_reused=persistence_result.request_id_reused,
    )

    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)

    return WebChatResponse(
        request_id=chat_response["request_id"],
        answer=chat_response["answer"],
        escalated=bool(chat_response["escalated"]),
        handoff_reasons=list(chat_response["handoff_reasons"]),
        references=list(chat_response["references"]),
        support_code=chat_response["request_id"],
        error_code=chat_response["error_code"],
    )


@router.post("/feedback", response_model=FeedbackResponse)
def create_web_feedback(
    payload: WebFeedbackRequest,
    request: Request,
    response: Response,
) -> FeedbackResponse:
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    feedback_payload = FeedbackRequest(
        request_id=payload.request_id,
        session_id=session_id,
        helpful=payload.helpful,
        reason=payload.reason,
        comment=payload.comment,
        source="web",
    )
    try:
        feedback_response = FeedbackService(request.app.state.database_runtime).record(
            feedback_payload
        )
    except FeedbackIntegrityConflictError as exc:
        raise HTTPException(status_code=409, detail="feedback_idempotency_conflict") from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="feedback_storage_unavailable") from exc
    log_event(
        logger,
        "feedback_recorded",
        request_id=get_request_id(request),
        chat_request_id=feedback_payload.request_id,
        session_id_hash=hash_sensitive_value(
            session_id,
            secret=settings.persistence_hash_secret,
        ),
        helpful=feedback_payload.helpful,
        reason_present=feedback_payload.reason is not None,
        comment_present=feedback_payload.comment is not None,
        source=feedback_payload.source,
        escalated=feedback_payload.escalated,
        handoff_reason_count=len(feedback_payload.handoff_reasons),
        reference_count=len(feedback_payload.references),
        error_code_present=feedback_payload.error_code is not None,
        storage=feedback_response.storage,
        context_status=feedback_response.status,
    )

    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)

    return feedback_response


def _load_default_domain(settings):
    domain = DomainLoader(settings.domains_path).load(settings.default_domain)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


def _log_web_chat_event(
    *,
    request_id: str,
    session_id: str,
    chat_response: dict[str, object],
    request_id_reused: bool,
) -> None:
    settings = get_settings()
    observability = chat_response.get("observability", {})
    observability_fields = observability if isinstance(observability, dict) else {}
    references = chat_response.get("references", [])
    handoff_reasons = chat_response.get("handoff_reasons", [])
    log_event(
        logger,
        "web_chat_completed",
        request_id=request_id,
        domain=chat_response["domain"],
        session_id_hash=hash_sensitive_value(
            session_id,
            secret=settings.persistence_hash_secret,
        ),
        confidence=chat_response["confidence"],
        escalated=chat_response["escalated"],
        handoff_reasons=handoff_reasons,
        error_code=chat_response["error_code"],
        handoff_status=chat_response["handoff_status"],
        persistence_status=chat_response["persistence_status"],
        request_id_reused=request_id_reused,
        channel="web",
        retrieval_backend=settings.retrieval_backend,
        references_count=len(references if isinstance(references, list) else []),
        total_ms=observability_fields.get("total_ms"),
        retrieval_ms=observability_fields.get("retrieval_ms"),
        llm_ms=observability_fields.get("llm_ms"),
    )
