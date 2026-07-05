import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.schemas.web_handoff import HandoffConsentRequest, HandoffConsentResponse
from app.core.config import get_settings
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.core.web_session import get_or_create_public_session_id, set_public_session_cookie
from app.identity.current import CurrentIdentityResolver
from app.db.operational import (
    ConsentCaseNotFound,
    InvalidConsentContact,
    OperationalRepository,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/consent", response_model=HandoffConsentResponse)
def confirm_handoff_consent(
    payload: HandoffConsentRequest,
    request: Request,
    response: Response,
) -> HandoffConsentResponse:
    settings = get_settings()
    if not settings.enable_handoff_consent_gate:
        raise HTTPException(status_code=404, detail="Not Found")

    session_id, should_set_cookie = get_or_create_public_session_id(request, settings)
    identity = CurrentIdentityResolver(
        settings=settings,
        web_auth_service=(
            request.app.state.web_auth_runtime.service
            if settings.enable_web_whatsapp_auth
            else None
        ),
    ).resolve(session_id)

    if not identity.authenticated or not identity.customer_id:
        # Never lets a caller reach a support_case without proving the OTP first
        # -- this is the gate the whole sprint exists for.
        raise HTTPException(status_code=401, detail="otp_confirmation_required")

    repository = OperationalRepository(request.app.state.database_runtime)
    try:
        result = repository.promote_pending_consent(
            request_id=payload.request_id,
            customer_id=identity.customer_id,
            name=payload.name,
            email=payload.email,
        )
    except ConsentCaseNotFound as exc:
        raise HTTPException(status_code=404, detail="support_case_not_found") from exc
    except InvalidConsentContact as exc:
        raise HTTPException(status_code=422, detail="invalid_email") from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="handoff_consent_storage_unavailable"
        ) from exc

    log_event(
        logger,
        "handoff_consent_confirmed",
        request_id=get_request_id(request),
        chat_request_id=payload.request_id,
        support_case_id=result.support_case_id,
        already_promoted=result.already_promoted,
    )

    if should_set_cookie:
        set_public_session_cookie(response, settings, session_id)

    return HandoffConsentResponse(
        support_case_id=result.support_case_id,
        status=result.status,
        opened_at=result.opened_at.isoformat() if result.opened_at else "",
        summary=result.summary,
        domain=result.domain,
        customer_name=result.customer_name,
        support_deep_link=result.support_deep_link,
    )
