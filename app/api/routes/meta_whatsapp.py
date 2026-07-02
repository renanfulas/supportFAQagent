from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.integrations.meta_whatsapp.chat_transport import (
    MetaWhatsAppChatTransport,
    MetaWhatsAppChatTransportError,
)
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.webhook import (
    parse_meta_webhook_payload,
    verify_meta_signature,
)


router = APIRouter()
logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 262_144
SAFE_META_ERROR_RE = re.compile(r"^meta_whatsapp_[a-z0-9_]{1,80}$")


@router.get("/webhook", response_class=PlainTextResponse)
def verify_webhook(
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = request.app.state.settings
    _ensure_enabled(settings)
    if (
        hub_mode == "subscribe"
        and hub_challenge
        and settings.meta_whatsapp_webhook_verify_token
        and hub_verify_token == settings.meta_whatsapp_webhook_verify_token
    ):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="meta_webhook_verification_failed")


@router.post("/webhook")
async def receive_webhook(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    _ensure_enabled(settings)
    body = await request.body()
    if not body or len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="invalid_meta_webhook_payload")
    if not verify_meta_signature(
        body=body,
        signature=request.headers.get("X-Hub-Signature-256"),
        app_secret=settings.meta_whatsapp_app_secret or "",
    ):
        log_event(
            logger,
            "meta_whatsapp_webhook_rejected",
            request_id=get_request_id(request),
            error_code="invalid_meta_webhook_signature",
        )
        raise HTTPException(status_code=401, detail="invalid_meta_webhook_signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_meta_webhook_payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_meta_webhook_payload")
    parsed = parse_meta_webhook_payload(payload)
    log_event(
        logger,
        "meta_whatsapp_webhook_received",
        request_id=get_request_id(request),
        messages_count=len(parsed.messages),
        statuses_count=len(parsed.statuses),
    )
    if settings.enable_meta_whatsapp_chat and parsed.messages:
        transport = MetaWhatsAppChatTransport(
            settings=settings,
            database_runtime=request.app.state.database_runtime,
            client=MetaWhatsAppClient(
                access_token=settings.meta_whatsapp_access_token or "",
                phone_number_id=settings.meta_whatsapp_phone_number_id or "",
                graph_api_version=settings.meta_whatsapp_graph_api_version,
                timeout_seconds=settings.meta_whatsapp_request_timeout_seconds,
            ),
            chat_session_state_store=getattr(
                request.app.state, "chat_session_state_store", None
            ),
            last_out_store=getattr(
                request.app.state, "session_last_out_store", None
            ),
        )
        try:
            for message in parsed.messages:
                transport.handle_text_message(
                    message=message,
                    request_id=get_request_id(request),
                )
        except MetaWhatsAppChatTransportError as exc:
            raise HTTPException(
                status_code=503,
                detail=_safe_meta_error_detail(str(exc)),
            ) from exc
        except Exception as exc:
            log_event(
                logger,
                "meta_whatsapp_chat_processing_failed",
                request_id=get_request_id(request),
                error_code=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="meta_whatsapp_chat_processing_failed",
            ) from exc
    return {"status": "accepted"}


def _ensure_enabled(settings) -> None:
    if not settings.enable_meta_whatsapp_webhook:
        raise HTTPException(status_code=404, detail="Not Found")


def _safe_meta_error_detail(value: str) -> str:
    detail = value.strip()
    if SAFE_META_ERROR_RE.fullmatch(detail):
        return detail
    return "meta_whatsapp_chat_processing_failed"
