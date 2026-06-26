from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request

from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.integrations.hermes.chat_transport import (
    HermesChatTransport,
    HermesChatTransportError,
)
from app.integrations.hermes.client import HermesBridgeClient
from app.integrations.hermes.inbound import (
    parse_hermes_inbound,
    verify_hermes_signature,
)


router = APIRouter()
logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 262_144
MAX_MESSAGES_PER_REQUEST = 25
# Hard cap on a single inbound message body before it reaches the LLM, to bound token
# cost and prompt-stuffing abuse even within the 256 KB request envelope.
MAX_MESSAGE_TEXT_CHARS = 4_096
PROXY_HEADERS = ("X-Forwarded-For", "X-Real-IP", "X-Forwarded-Host")
SAFE_ERROR_RE = re.compile(r"^hermes_[a-z0-9_]{1,80}$")


@router.post("/chat/webhook")
async def receive_chat_webhook(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    if not settings.enable_hermes_chat:
        raise HTTPException(status_code=404, detail="Not Found")

    # Internal endpoint: the bridge calls 127.0.0.1:8000 directly. Anything arriving
    # through the public reverse proxy carries forwarding headers — reject it so the
    # webhook is never reachable from the internet, only from the local bridge.
    if any(request.headers.get(header) for header in PROXY_HEADERS):
        raise HTTPException(status_code=404, detail="Not Found")

    # Reject oversized payloads from the advertised length before buffering the whole
    # body into memory. The post-read length check below still guards a lying header.
    declared_length = request.headers.get("Content-Length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="invalid_hermes_payload")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_hermes_payload") from exc

    body = await request.body()
    if not body or len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="invalid_hermes_payload")
    # Dedicated secret for the inbound chat forward, segregated from the OTP secret.
    # Falls back to the OTP secret only if a dedicated one is not configured.
    forward_secret = settings.hermes_chat_forward_secret or settings.hermes_webhook_secret or ""
    signature = request.headers.get("X-Webhook-Signature")
    if not verify_hermes_signature(
        body=body,
        signature=signature,
        timestamp=request.headers.get("X-Webhook-Timestamp"),
        secret=forward_secret,
    ):
        log_event(
            logger,
            "hermes_chat_webhook_rejected",
            request_id=get_request_id(request),
            error_code="invalid_hermes_signature",
        )
        raise HTTPException(status_code=401, detail="invalid_hermes_signature")

    # The HMAC only covers the body, so an identical signed request is replayable inside
    # the freshness window. Reject any signature already seen within that window.
    replay_guard = getattr(request.app.state, "hermes_replay_guard", None)
    if replay_guard is not None and not replay_guard.check_and_remember(signature or ""):
        log_event(
            logger,
            "hermes_chat_webhook_rejected",
            request_id=get_request_id(request),
            error_code="hermes_replayed_signature",
        )
        raise HTTPException(status_code=409, detail="hermes_replayed_signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_hermes_payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_hermes_payload")

    messages = parse_hermes_inbound(payload, max_text_chars=MAX_MESSAGE_TEXT_CHARS)
    if len(messages) > MAX_MESSAGES_PER_REQUEST:
        raise HTTPException(status_code=400, detail="too_many_messages")
    log_event(
        logger,
        "hermes_chat_webhook_received",
        request_id=get_request_id(request),
        messages_count=len(messages),
    )
    if not messages:
        return {"status": "accepted"}

    transport = HermesChatTransport(
        settings=settings,
        database_runtime=request.app.state.database_runtime,
        client=HermesBridgeClient(
            base_url=settings.hermes_bridge_url,
            timeout_seconds=settings.hermes_request_timeout_seconds,
        ),
        session_store=getattr(request.app.state, "session_domain_store", None),
        state_store=getattr(request.app.state, "session_state_store", None),
        last_out_store=getattr(request.app.state, "session_last_out_store", None),
    )
    try:
        for message in messages:
            transport.handle_text_message(
                message=message,
                request_id=get_request_id(request),
            )
    except HermesChatTransportError as exc:
        raise HTTPException(status_code=503, detail=_safe_error_detail(str(exc))) from exc
    except Exception as exc:
        log_event(
            logger,
            "hermes_chat_processing_failed",
            request_id=get_request_id(request),
            error_code=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="hermes_chat_processing_failed") from exc
    return {"status": "accepted"}


def _safe_error_detail(value: str) -> str:
    detail = value.strip()
    if SAFE_ERROR_RE.fullmatch(detail):
        return detail
    return "hermes_chat_processing_failed"
