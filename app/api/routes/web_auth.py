import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.schemas.web_auth import (
    AnonymousSessionResponse,
    VerifiedSessionResponse,
    WhatsAppOtpConfirmRequest,
    WhatsAppOtpStartRequest,
    WhatsAppOtpStartResponse,
)
from app.core.config import get_settings
from app.core.logging import log_event
from app.core.rate_limit import RateLimitExceeded
from app.core.request_context import get_request_id
from app.core.web_session import get_or_create_public_session_id, set_public_session_cookie
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.runtime import WebAuthRuntime
from app.web_auth.service import InvalidOrExpiredCode, ResendCooldown


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/whatsapp/start", response_model=WhatsAppOtpStartResponse, status_code=202)
def start_whatsapp_otp(
    payload: WhatsAppOtpStartRequest,
    request: Request,
    response: Response,
) -> WhatsAppOtpStartResponse:
    runtime = _get_runtime(request)
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    try:
        challenge = runtime.service.start(
            phone=payload.phone,
            client_host=request.client.host if request.client else "unknown",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_phone") from exc
    except (RateLimitExceeded, ResendCooldown) as exc:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except OtpDeliveryUnavailable as exc:
        raise HTTPException(status_code=503, detail="otp_delivery_unavailable") from exc

    log_event(
        logger,
        "web_whatsapp_otp_started",
        request_id=get_request_id(request),
        challenge_id=challenge.id,
        phone_hash=challenge.phone_hash,
    )
    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)
    return WhatsAppOtpStartResponse(
        challenge_id=challenge.id,
        expires_in_seconds=settings.otp_code_ttl_seconds,
        retry_after_seconds=settings.otp_resend_cooldown_seconds,
        abandonment_reminder_seconds=settings.otp_abandonment_reminder_minutes * 60,
    )


@router.post("/whatsapp/confirm", response_model=VerifiedSessionResponse)
def confirm_whatsapp_otp(
    payload: WhatsAppOtpConfirmRequest,
    request: Request,
    response: Response,
) -> VerifiedSessionResponse:
    runtime = _get_runtime(request)
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    try:
        identity = runtime.service.confirm(
            challenge_id=payload.challenge_id,
            code=payload.code,
            session_id=session_id,
        )
    except InvalidOrExpiredCode as exc:
        raise HTTPException(status_code=400, detail="invalid_or_expired_code") from exc

    log_event(
        logger,
        "web_whatsapp_otp_verified",
        request_id=get_request_id(request),
        challenge_id=payload.challenge_id,
        phone_hash=identity.phone_hash,
    )
    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)
    return VerifiedSessionResponse(phone_last4=identity.phone_last4)


@router.get("/session", response_model=AnonymousSessionResponse | VerifiedSessionResponse)
def get_web_auth_session(
    request: Request,
    response: Response,
) -> AnonymousSessionResponse | VerifiedSessionResponse:
    runtime = _get_runtime(request)
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    identity = runtime.service.get_session_identity(session_id)
    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)
    if identity is None:
        return AnonymousSessionResponse()
    return VerifiedSessionResponse(phone_last4=identity.phone_last4)


@router.post("/logout", response_model=AnonymousSessionResponse)
def logout_web_auth_session(
    request: Request,
    response: Response,
) -> AnonymousSessionResponse:
    runtime = _get_runtime(request)
    settings = get_settings()
    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    runtime.service.logout(session_id)
    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)
    return AnonymousSessionResponse()


def _get_runtime(request: Request) -> WebAuthRuntime:
    settings = get_settings()
    if not settings.enable_web_whatsapp_auth:
        raise HTTPException(status_code=404, detail="Not Found")
    return request.app.state.web_auth_runtime
