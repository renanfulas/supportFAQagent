from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request
import requests
from starlette.concurrency import run_in_threadpool

from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.core.errors import DatabaseUnavailableError
from app.integrations.webhook_ingress import (
    DUPLICATE,
    IN_PROGRESS,
    PAYLOAD_CONFLICT,
    WebhookIngressRepository,
    payload_hash,
    verify_signature,
)


router = APIRouter()
logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 65_536
EVENT_URL_FIELDS = {
    "handoff.requested": "n8n_verified_handoff_url",
    "whatsapp.message.requested": "n8n_verified_whatsapp_url",
    "otp.delivery.requested": "n8n_verified_otp_url",
}


@router.post("/outbox/{event_type:path}")
async def receive_outbox_event(
    event_type: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    timestamp: str | None = Header(default=None, alias="X-Webhook-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
) -> dict[str, str]:
    settings = request.app.state.settings
    request_id = get_request_id(request)
    if not settings.enable_outbox_ingress:
        raise HTTPException(status_code=404, detail="Not found")
    if event_type not in EVENT_URL_FIELDS:
        raise HTTPException(status_code=404, detail="unknown_event_type")
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="invalid_idempotency_key")

    body = await request.body()
    if not body or len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="invalid_webhook_payload")
    if not verify_signature(
        body=body,
        timestamp=timestamp,
        signature=signature,
        secret=settings.outbox_webhook_secret or "",
    ):
        log_event(
            logger,
            "webhook_ingress_rejected",
            request_id=request_id,
            event_type=event_type,
            error_code="invalid_webhook_signature",
        )
        raise HTTPException(status_code=401, detail="invalid_webhook_signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_webhook_payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_webhook_payload")

    repository = WebhookIngressRepository(request.app.state.database_runtime)
    try:
        claim = repository.claim(
            event_type=event_type,
            idempotency_key=idempotency_key,
            request_id=request_id,
            body_hash=payload_hash(body),
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="webhook_ingress_storage_unavailable") from exc
    if claim.status == PAYLOAD_CONFLICT:
        raise HTTPException(status_code=409, detail="idempotency_payload_conflict")
    if claim.status == IN_PROGRESS:
        raise HTTPException(status_code=425, detail="delivery_in_progress")
    if claim.status == DUPLICATE:
        return {"status": "duplicate", "request_id": request_id}

    target_url = getattr(settings, EVENT_URL_FIELDS[event_type])
    if not target_url:
        _mark_failed(repository, idempotency_key, "verified_webhook_not_configured")
        raise HTTPException(status_code=503, detail="verified_webhook_not_configured")
    try:
        response = await run_in_threadpool(
            requests.post,
            target_url,
            json=payload,
            headers={"X-Request-ID": request_id, "X-Idempotency-Key": idempotency_key},
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        _mark_failed(repository, idempotency_key, "verified_webhook_delivery_failed")
        log_event(
            logger,
            "webhook_ingress_delivery_failed",
            request_id=request_id,
            event_type=event_type,
            attempt_count=claim.attempt_count,
            error_code="verified_webhook_delivery_failed",
        )
        raise HTTPException(status_code=502, detail="verified_webhook_delivery_failed") from exc

    try:
        repository.mark_delivered(idempotency_key)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="webhook_ingress_storage_unavailable") from exc
    log_event(
        logger,
        "webhook_ingress_delivered",
        request_id=request_id,
        event_type=event_type,
        attempt_count=claim.attempt_count,
    )
    return {"status": "delivered", "request_id": request_id}


def _mark_failed(
    repository: WebhookIngressRepository,
    idempotency_key: str,
    error_code: str,
) -> None:
    try:
        repository.mark_failed(idempotency_key, error_code)
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="webhook_ingress_storage_unavailable") from exc
