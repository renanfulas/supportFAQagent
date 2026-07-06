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
from app.identity.native_history_link import NativeHistoryLinkRepository
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
        confirmed = runtime.service.confirm(
            challenge_id=payload.challenge_id,
            code=payload.code,
            session_id=session_id,
        )
    except InvalidOrExpiredCode as exc:
        raise HTTPException(status_code=400, detail="invalid_or_expired_code") from exc

    identity = confirmed.identity
    log_event(
        logger,
        "web_whatsapp_otp_verified",
        request_id=get_request_id(request),
        challenge_id=payload.challenge_id,
        phone_hash=identity.phone_hash,
    )
    _maybe_link_native_history(request, confirmed)
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


def _maybe_link_native_history(request: Request, confirmed) -> None:
    """Fase 3 (opcional, opt-in): backfill best-effort do historico do
    WhatsApp nativo para o customer_id que acabou de provar o telefone via
    OTP. Nunca falha a resposta do OTP -- so registra em log; o cliente ja
    esta autenticado independente disso."""

    settings = get_settings()
    if not getattr(settings, "enable_native_identity_link", False):
        return
    if confirmed.native_session_hashes is None or confirmed.identity.customer_id is None:
        return
    if settings.persistence_backend != "postgres":
        return
    try:
        result = NativeHistoryLinkRepository(request.app.state.database_runtime).link(
            customer_id=confirmed.identity.customer_id,
            hashes=confirmed.native_session_hashes,
        )
        log_event(
            logger,
            "native_identity_link_applied",
            request_id=get_request_id(request),
            conversations_linked=result.conversations_linked,
            support_cases_linked=result.support_cases_linked,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort, never blocks login
        log_event(
            logger,
            "native_identity_link_unavailable",
            request_id=get_request_id(request),
            error_type=type(exc).__name__,
        )
