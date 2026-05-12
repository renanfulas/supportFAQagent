import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import verify_api_key
from app.domain_engine.loader import DomainLoader
from app.orchestration.chat_flow import ChatFlowService


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    _: str = Depends(verify_api_key),
) -> ChatResponse:
    request_id = get_request_id(request)
    settings = get_settings()
    domain_name = payload.domain or settings.default_domain
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(domain_name)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    response = ChatFlowService().answer(
        domain=domain,
        question=payload.message,
        session_id=payload.session_id,
        request_id=request_id,
    )
    log_event(
        logger,
        "chat_completed",
        request_id=request_id,
        domain=response["domain"],
        session_id_hash=hash_sensitive_value(payload.session_id),
        confidence=response["confidence"],
        escalated=response["escalated"],
        handoff_reasons=response["handoff_reasons"],
        error_code=response["error_code"],
    )
    return ChatResponse(**response)
