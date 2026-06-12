import logging
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value
from app.core.request_context import get_request_id
from app.core.security import (
    API_KEY_HEADER_NAME,
    is_valid_api_key,
    is_valid_secret,
    verify_api_key,
)
from app.domain_engine.loader import DomainLoader
from app.conversations.service import ConversationHistoryService
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_UNAVAILABLE,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime
from app.orchestration.chat_flow import ChatFlowService


router = APIRouter()
logger = logging.getLogger(__name__)
WEBHOOK_TOKEN_QUERY_PARAM = "token"


class ZoomJoinRequest(BaseModel):
    meeting_url: str
    bot_name: str = "SupportBot Fantasma"
    webhook_url: str
    domain: Optional[str] = None


def send_chat_to_zoom(bot_id: str, message: str) -> None:
    settings = get_settings()
    if not settings.recall_api_key:
        log_event(
            logger,
            "zoom_send_skipped",
            reason="missing_recall_api_key",
            bot_id_hash=hash_sensitive_value(bot_id),
        )
        return

    try:
        url = f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/send_chat_message/"
        headers = {"Authorization": f"Token {settings.recall_api_key}"}
        body = {"message": message, "to": "everyone"}
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        log_event(
            logger,
            "zoom_send_failed",
            bot_id_hash=hash_sensitive_value(bot_id),
            error_type=type(exc).__name__,
        )


def process_and_reply(
    question: str,
    bot_id: str,
    domain_name: Optional[str],
    request_id: str,
    database_runtime: DatabaseRuntime,
) -> None:
    settings = get_settings()
    domain_to_load = domain_name or settings.default_domain
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(domain_to_load)

    if not domain:
        log_event(
            logger,
            "zoom_webhook_domain_not_found",
            request_id=request_id,
            domain=domain_to_load,
            bot_id_hash=hash_sensitive_value(bot_id),
        )
        return

    try:
        response = ChatFlowService(
            history_service=ConversationHistoryService(database_runtime),
        ).answer(
            domain=domain,
            question=question,
            session_id=bot_id,
            request_id=request_id,
            channel="zoom",
        )
        persistence_result = OperationalRepository(database_runtime).record_chat(
            ChatAuditInput(
                request_id=request_id,
                domain=str(response["domain"]),
                session_id=bot_id,
                question=question,
                answer=str(response["answer"]),
                confidence=float(response["confidence"]),
                escalated=bool(response["escalated"]),
                handoff_reasons=list(response["handoff_reasons"]),
                references=list(response["references"]),
                error_code=response["error_code"],
                channel="zoom",
            )
        )
        answer_text = response.get(
            "answer",
            "Desculpe, nao consegui processar sua duvida.",
        )
        if persistence_result.handoff_status == HANDOFF_UNAVAILABLE:
            answer_text = (
                f"{answer_text} O atendimento humano esta temporariamente "
                "indisponivel; guarde o request_id para acompanhamento."
            )
        send_chat_to_zoom(bot_id, answer_text)
    except Exception as exc:
        log_event(
            logger,
            "zoom_webhook_processing_failed",
            request_id=request_id,
            bot_id_hash=hash_sensitive_value(bot_id),
            error_type=type(exc).__name__,
        )


def _append_webhook_token(webhook_url: str, webhook_secret: str | None) -> str:
    if not webhook_secret:
        return webhook_url

    split_result = urlsplit(webhook_url)
    query_items = dict(parse_qsl(split_result.query, keep_blank_values=True))
    query_items[WEBHOOK_TOKEN_QUERY_PARAM] = webhook_secret
    return urlunsplit(
        (
            split_result.scheme,
            split_result.netloc,
            split_result.path,
            urlencode(query_items),
            split_result.fragment,
        )
    )


def _is_valid_webhook_request(request: Request, webhook_token: str | None) -> bool:
    if is_valid_api_key(request.headers.get(API_KEY_HEADER_NAME)):
        return True

    return is_valid_secret(webhook_token, get_settings().zoom_webhook_secret)


@router.post("/join", summary="Pede para o bot fantasma entrar na reuniao")
def join_meeting(
    payload: ZoomJoinRequest,
    request: Request,
    _: str = Depends(verify_api_key),
):
    request_id = get_request_id(request)
    log_event(
        logger,
        "zoom_join_requested",
        request_id=request_id,
        meeting_url_hash=hash_sensitive_value(payload.meeting_url),
    )

    settings = get_settings()
    if not settings.recall_api_key:
        raise HTTPException(status_code=503, detail="zoom_provider_unavailable")

    try:
        webhook_url = _append_webhook_token(
            payload.webhook_url,
            settings.zoom_webhook_secret,
        )
        url = "https://us-west-2.recall.ai/api/v1/bot"
        headers = {"Authorization": f"Token {settings.recall_api_key}"}
        body = {
            "meeting_url": payload.meeting_url,
            "bot_name": payload.bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": webhook_url,
                        "events": ["participant_events.chat_message"],
                    }
                ]
            },
        }
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
        bot_data = response.json()

        return {
            "status": "success",
            "message": "Comando enviado. O bot esta a caminho da sala de espera.",
            "bot_id": bot_data.get("id"),
            "meeting_url": payload.meeting_url,
        }
    except requests.exceptions.HTTPError as exc:
        log_event(
            logger,
            "zoom_join_failed",
            request_id=request_id,
            error_type=type(exc).__name__,
            error_code="zoom_provider_rejected_request",
        )
        raise HTTPException(status_code=502, detail="zoom_provider_rejected_request") from exc
    except Exception as exc:
        log_event(
            logger,
            "zoom_join_failed",
            request_id=request_id,
            error_type=type(exc).__name__,
            error_code="zoom_provider_unavailable",
        )
        raise HTTPException(
            status_code=502,
            detail="zoom_provider_unavailable",
        ) from exc


@router.post("/webhook", summary="Recebe os eventos do bot fantasma")
def zoom_webhook(
    payload: dict,
    request: Request,
    background_tasks: BackgroundTasks,
    token: str | None = Query(default=None, alias=WEBHOOK_TOKEN_QUERY_PARAM),
):
    request_id = get_request_id(request)
    if not _is_valid_webhook_request(request, token):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    event_name = payload.get("event", "unknown_event")
    data = payload.get("data", payload)
    log_event(
        logger,
        "zoom_webhook_received",
        request_id=request_id,
        webhook_event=event_name,
        has_data=isinstance(data, dict),
    )

    if event_name == "participant_events.chat_message":
        try:
            event_data = data.get("data", {})
            chat_text = event_data.get("data", {}).get("text", "")
            sender = event_data.get("participant", {}).get("name", "")
            bot_id = data.get("bot", {}).get("id", "")
            domain_name = data.get("domain")
        except Exception as exc:
            log_event(
                logger,
                "zoom_webhook_parse_failed",
                request_id=request_id,
                webhook_event=event_name,
                error_type=type(exc).__name__,
            )
            return {"status": "error", "detail": "Invalid payload format"}

        if "support" in sender.lower() or "bot" in sender.lower() or "agent" in sender.lower():
            return {"status": "ignored"}

        trigger_words = ["bot", "support", "faq", "agent", "@"]
        if any(word in chat_text.lower() for word in trigger_words):
            log_event(
                logger,
                "zoom_webhook_chat_queued",
                request_id=request_id,
                webhook_event=event_name,
                sender_hash=hash_sensitive_value(sender),
                bot_id_hash=hash_sensitive_value(bot_id),
                domain=domain_name,
            )
            background_tasks.add_task(
                process_and_reply,
                chat_text,
                bot_id,
                domain_name,
                request_id,
                request.app.state.database_runtime,
            )
            return {"status": "processing"}

    return {"status": "received"}
