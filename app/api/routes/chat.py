from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.orchestration.chat_flow import ChatFlowService


router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    request_id = str(uuid4())
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
    return ChatResponse(**response)
