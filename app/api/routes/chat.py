import logging
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.core.config import DEV_ENVS, Settings, get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import API_KEY_HEADER_NAME, is_valid_api_key
from app.domain_engine.loader import DomainLoader
from app.orchestration.chat_flow import ChatFlowService


router = APIRouter()
logger = logging.getLogger(__name__)
LLM_API_KEY_HEADER_NAME = "X-LLM-API-Key"


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    llm_api_key: str | None = Header(
        default=None,
        alias=LLM_API_KEY_HEADER_NAME,
        max_length=4096,
    ),
) -> ChatResponse:
    request_id = get_request_id(request)
    settings = get_settings()
    provider_api_key = _resolve_provider_api_key(llm_api_key, settings)
    _verify_chat_access(request, settings, raw_provider_api_key=llm_api_key)
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
        provider_api_key=provider_api_key,
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


def _verify_chat_access(
    request: Request,
    settings: Settings,
    raw_provider_api_key: str | None,
) -> None:
    if is_valid_api_key(request.headers.get(API_KEY_HEADER_NAME)):
        return

    if (
        _allows_provider_key_for_chat_ui(settings)
        and raw_provider_api_key
        and raw_provider_api_key.strip()
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid API key",
    )


def _allows_provider_key_for_chat_ui(settings: Settings) -> bool:
    app_env = settings.app_env.lower()
    return app_env in DEV_ENVS or (settings.enable_chat_ui and app_env != "production")


def _resolve_provider_api_key(
    raw_provider_api_key: str | None,
    settings: Settings,
) -> str | None:
    if raw_provider_api_key is None:
        return None

    provider_api_key = raw_provider_api_key.strip()
    if not provider_api_key:
        return None

    alias = settings.project_llm_api_key_alias
    if alias and hmac.compare_digest(provider_api_key, alias):
        return None

    return provider_api_key
