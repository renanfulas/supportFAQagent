import logging
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.schemas.chat import ChatRequest, ChatResponse
from app.core.config import DEV_ENVS, Settings, get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import API_KEY_HEADER_NAME, is_valid_secret
from app.domain_engine.loader import DomainLoader
from app.conversations.service import ConversationHistoryService
from app.orchestration.chat_flow import ChatFlowService
from app.db.operational import ChatAuditInput, HANDOFF_UNAVAILABLE, OperationalRepository


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

    database_runtime = request.app.state.database_runtime
    response = ChatFlowService(
        history_service=ConversationHistoryService(database_runtime),
    ).answer(
        domain=domain,
        question=payload.message,
        session_id=payload.session_id,
        request_id=request_id,
        provider_api_key=provider_api_key,
        channel=payload.channel,
    )
    persistence_result = OperationalRepository(database_runtime).record_chat(
        ChatAuditInput(
            request_id=request_id,
            domain=str(response["domain"]),
            session_id=payload.session_id,
            question=payload.message,
            answer=str(response["answer"]),
            confidence=float(response["confidence"]),
            escalated=bool(response["escalated"]),
            handoff_reasons=list(response["handoff_reasons"]),
            references=list(response["references"]),
            error_code=response["error_code"],
            channel=payload.channel,
        )
    )
    response["handoff_status"] = persistence_result.handoff_status
    response["persistence_status"] = persistence_result.persistence_status
    if response["handoff_status"] == HANDOFF_UNAVAILABLE:
        response["answer"] = (
            f"{response['answer']} O atendimento humano esta temporariamente indisponivel; "
            "guarde o request_id para acompanhamento."
        )
    observability = response.get("observability", {})
    observability_fields = observability if isinstance(observability, dict) else {}
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
        handoff_status=response["handoff_status"],
        persistence_status=response["persistence_status"],
        request_id_reused=persistence_result.request_id_reused,
        channel=payload.channel,
        retrieval_backend=settings.retrieval_backend,
        references_count=len(response["references"]),
        total_ms=observability_fields.get("total_ms"),
        retrieval_ms=observability_fields.get("retrieval_ms"),
        llm_ms=observability_fields.get("llm_ms"),
    )
    return ChatResponse(**response)


def _verify_chat_access(
    request: Request,
    settings: Settings,
    raw_provider_api_key: str | None,
) -> None:
    if is_valid_secret(request.headers.get(API_KEY_HEADER_NAME), settings.api_secret_key):
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
