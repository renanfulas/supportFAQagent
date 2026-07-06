"""Fachada web staff do console de suporte (/web/support/*).

Area interna do time sobre o support inbox existente: nada de canal paralelo
de dados, nada de segredo no browser. Auth por OTP WhatsApp dedicado
(``staff_members``/``staff_sessions``), sessao em cookie ``HttpOnly`` restrito
a ``Path=/web/support`` e leitura da fila com semaforo de SLA calculado em
Python sobre o relogio do banco. Dark por padrao: ``ENABLE_SUPPORT_CONSOLE``
desligada responde ``404`` em toda a superficie, inclusive auth.

Logs seguem a regra do produto: sem PII, sem token, sem transcript; hashes
sempre truncados.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes.support import (
    _ALLOWED_STATUSES,
    _context_to_response,
    _summary_to_response,
)
from app.api.schemas.web_support import (
    ConsoleAssigneeResponse,
    ConsoleCaseDetailResponse,
    ConsoleCaseEventResponse,
    ConsoleCaseListResponse,
    ConsoleCaseMessageRequest,
    ConsoleCaseMessageResponse,
    ConsoleCaseSummaryResponse,
    ConsoleMetricsResponse,
    ConsoleSlaResponse,
    StaffLoginResponse,
    StaffLogoutRequest,
    StaffLogoutResponse,
    StaffOtpConfirmRequest,
    StaffOtpStartRequest,
    StaffOtpStartResponse,
    StaffSessionResponse,
    StaffTransitionRequest,
    StaffTransitionResponse,
)
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.rate_limit import RateLimitExceeded
from app.core.request_context import get_request_id
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.support.metrics import WINDOW_DAYS, SupportMetricsRepository, build_console_metrics
from app.support.repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SupportCaseRepository,
    SupportCaseSummary,
)
from app.support.whatsapp_bridge import (
    CaseHasNoBinding,
    SupportWhatsAppBridgeService,
    SupportWhatsAppWindowClosed,
)
from app.support.sla import (
    COLOR_FILTERS,
    SlaAssessment,
    attention_sort_key,
    compute_sla,
    matches_color_filter,
)
from app.support.staff_auth import (
    StaffConsoleAuthService,
    StaffPhoneRequired,
    StaffPrincipal,
    SupportConsoleRuntime,
)
from app.support.transitions import (
    CaseNotFound,
    InvalidTransition,
    SupportCaseTransitionService,
)
from app.web_auth.service import InvalidOrExpiredCode


router = APIRouter()
logger = logging.getLogger(__name__)

STAFF_SESSION_COOKIE = "sfa_staff_session"
STAFF_HINT_COOKIE = "sfa_staff_hint"
STAFF_SESSION_COOKIE_PATH = "/web/support"
# O lembrete e ainda mais restrito: so viaja para os endpoints de auth.
STAFF_HINT_COOKIE_PATH = "/web/support/auth"

_ACTIVE_SORTS = {"attention", "opened_at"}
_VIEWS = {"active", "history"}
_ASSIGNEE_FILTERS = {"me"}
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"


def _ensure_enabled(request: Request) -> None:
    if not request.app.state.settings.enable_support_console:
        raise HTTPException(status_code=404, detail="Not found")


def _get_runtime(request: Request) -> SupportConsoleRuntime:
    _ensure_enabled(request)
    return request.app.state.support_console_runtime


def _get_service(request: Request) -> StaffConsoleAuthService:
    return _get_runtime(request).service


def require_staff_session(request: Request) -> StaffPrincipal:
    """Route guard for everything under /web/support except auth/*."""

    runtime = _get_runtime(request)
    session_token = request.cookies.get(STAFF_SESSION_COOKIE)
    try:
        principal = runtime.service.get_session(session_token)
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc
    if principal is None:
        # Detail generico, sem eco de identificadores; o evento nomeado da
        # visibilidade de acesso negado sem vazar quem tentou.
        log_event(
            logger,
            "support_console_auth_denied",
            request_id=get_request_id(request),
            reason="no_valid_session",
        )
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        runtime.reads_limiter.check(session_token or "")
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    return principal


def _require_csrf_header(request: Request) -> None:
    """Escritas (Fase B) exigem o cabecalho, alem do `SameSite=Lax` do cookie."""

    if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="csrf_header_required")


@router.post("/auth/start", response_model=StaffOtpStartResponse, status_code=202)
def start_staff_otp(
    payload: StaffOtpStartRequest,
    request: Request,
) -> StaffOtpStartResponse:
    service = _get_service(request)
    settings = request.app.state.settings
    try:
        result = service.start(
            phone=payload.phone,
            hint_cookie=request.cookies.get(STAFF_HINT_COOKIE),
            client_host=request.client.host if request.client else "unknown",
        )
    except StaffPhoneRequired as exc:
        raise HTTPException(status_code=422, detail="invalid_phone") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_phone") from exc
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_console_auth_started",
        request_id=request_id,
        staff_match=result.staff_match,
        phone_hash_prefix=result.phone_hash_prefix,
    )
    if result.delivery_failed:
        # Falha de entrega nunca muda a resposta (side channel); vira log
        # interno e o operador pede outro codigo.
        log_event(
            logger,
            "support_console_auth_delivery_failed",
            request_id=request_id,
            phone_hash_prefix=result.phone_hash_prefix,
        )
    return StaffOtpStartResponse(
        challenge_id=result.challenge_id,
        expires_in_seconds=settings.otp_code_ttl_seconds,
        retry_after_seconds=settings.otp_resend_cooldown_seconds,
    )


@router.post("/auth/confirm", response_model=StaffLoginResponse)
def confirm_staff_otp(
    payload: StaffOtpConfirmRequest,
    request: Request,
    response: Response,
) -> StaffLoginResponse:
    service = _get_service(request)
    settings = request.app.state.settings
    try:
        login = service.confirm(
            challenge_id=payload.challenge_id,
            code=payload.code,
            phone=payload.phone,
            hint_cookie=request.cookies.get(STAFF_HINT_COOKIE),
        )
    except InvalidOrExpiredCode as exc:
        log_event(
            logger,
            "support_console_auth_denied",
            request_id=get_request_id(request),
            reason="invalid_or_expired_code",
        )
        raise HTTPException(status_code=400, detail="invalid_or_expired_code") from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    # O servidor e a fonte de verdade da expiracao; o Max-Age so acompanha.
    max_age = max(
        1,
        int((login.principal.expires_at - datetime.now(UTC)).total_seconds()),
    )
    response.set_cookie(
        key=STAFF_SESSION_COOKIE,
        value=login.session_token,
        max_age=max_age,
        path=STAFF_SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=bool(settings.web_chat_cookie_secure),
    )
    if login.hint_cookie_value:
        response.set_cookie(
            key=STAFF_HINT_COOKIE,
            value=login.hint_cookie_value,
            max_age=settings.support_staff_hint_ttl_days * 24 * 60 * 60,
            path=STAFF_HINT_COOKIE_PATH,
            httponly=True,
            samesite="lax",
            secure=bool(settings.web_chat_cookie_secure),
        )
    log_event(
        logger,
        "support_console_auth_confirmed",
        request_id=get_request_id(request),
        staff_id=login.principal.staff_id,
    )
    return StaffLoginResponse(
        display_name=login.principal.display_name,
        expires_at=login.principal.expires_at,
    )


@router.get("/auth/session")
def get_staff_session(request: Request) -> Response:
    service = _get_service(request)
    try:
        principal = service.get_session(request.cookies.get(STAFF_SESSION_COOKIE))
        if principal is not None:
            return JSONResponse(
                StaffSessionResponse(
                    display_name=principal.display_name,
                    expires_at=principal.expires_at,
                ).model_dump(mode="json"),
            )
        # 401 com o lembrete do dispositivo (se houver): e o que permite a
        # tela de login mostrar o botao de 1 clique "Entrar como <nome>".
        hint_name = service.get_hint_display_name(
            request.cookies.get(STAFF_HINT_COOKIE),
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc
    return JSONResponse(
        status_code=401,
        content={
            "authenticated": False,
            "hint": {"display_name": hint_name} if hint_name else None,
        },
    )


@router.post("/auth/logout", response_model=StaffLogoutResponse)
def logout_staff_session(
    request: Request,
    response: Response,
    payload: StaffLogoutRequest | None = None,
) -> StaffLogoutResponse:
    service = _get_service(request)
    forget_device = bool(payload and payload.forget_device)
    try:
        service.logout(
            session_token=request.cookies.get(STAFF_SESSION_COOKIE),
            forget_hint_cookie=(
                request.cookies.get(STAFF_HINT_COOKIE) if forget_device else None
            ),
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc
    response.delete_cookie(STAFF_SESSION_COOKIE, path=STAFF_SESSION_COOKIE_PATH)
    if forget_device:
        response.delete_cookie(STAFF_HINT_COOKIE, path=STAFF_HINT_COOKIE_PATH)
    return StaffLogoutResponse()


@router.get("/cases", response_model=ConsoleCaseListResponse)
def list_console_cases(
    request: Request,
    view: str = Query(default="active", max_length=20),
    domain: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    color: str | None = Query(default=None, max_length=10),
    sort: str = Query(default="attention", max_length=20),
    assignee: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseListResponse:
    if view not in _VIEWS:
        raise HTTPException(status_code=422, detail="invalid_view")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status_filter")
    if color is not None and color not in COLOR_FILTERS:
        raise HTTPException(status_code=422, detail="invalid_color_filter")
    if sort not in _ACTIVE_SORTS:
        raise HTTPException(status_code=422, detail="invalid_sort")
    if assignee is not None and assignee not in _ASSIGNEE_FILTERS:
        raise HTTPException(status_code=422, detail="invalid_assignee_filter")
    assignee_staff_id = principal.staff_id if assignee == "me" else None

    settings = request.app.state.settings
    repository = SupportCaseRepository(request.app.state.database_runtime)
    request_id = get_request_id(request)
    truncated = False
    try:
        if view == "history":
            summaries = repository.list_history_cases(
                domain=domain,
                status=status,
                limit=limit,
                offset=offset,
                assignee_staff_id=assignee_staff_id,
            )
            # Historico nao passa por SLA: paginacao SQL normal.
            cases = [
                ConsoleCaseSummaryResponse(
                    **_summary_to_response(case).model_dump(),
                    assignee=_assignee_from_summary(case),
                )
                for case in summaries
            ]
        else:
            active = repository.list_active_cases(
                domain=domain,
                status=status,
                cap=settings.support_console_active_cases_cap,
                assignee_staff_id=assignee_staff_id,
            )
            truncated = active.truncated
            if truncated:
                log_event(
                    logger,
                    "support_console_active_cap_reached",
                    request_id=request_id,
                    cap=settings.support_console_active_cases_cap,
                )
            assessed = [
                (case, _assess(case, active.db_now, settings))
                for case in active.cases
            ]
            if color is not None:
                assessed = [
                    item for item in assessed if matches_color_filter(item[1], color)
                ]
            if sort == "attention":
                assessed.sort(
                    key=lambda item: attention_sort_key(
                        priority=item[0].priority,
                        opened_at=item[0].opened_at,
                        sla=item[1],
                    ),
                )
            page = assessed[offset : offset + limit]
            cases = [
                ConsoleCaseSummaryResponse(
                    **_summary_to_response(case).model_dump(),
                    sla=_sla_to_response(sla),
                    assignee=_assignee_from_summary(case),
                )
                for case, sla in page
            ]
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    log_event(
        logger,
        "support_console_listed",
        request_id=request_id,
        view=view,
        domain_filter_present=domain is not None,
        status_filter=status,
        color_filter=color,
        sort=sort,
        assignee_filter=assignee,
        result_count=len(cases),
        truncated=truncated,
    )
    return ConsoleCaseListResponse(
        request_id=request_id,
        view=view,
        count=len(cases),
        limit=limit,
        offset=offset,
        truncated=truncated,
        cases=cases,
    )


@router.get("/cases/{case_id}", response_model=ConsoleCaseDetailResponse)
def get_console_case(
    case_id: str,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseDetailResponse:
    settings = request.app.state.settings
    repository = SupportCaseRepository(request.app.state.database_runtime)
    try:
        context = repository.get_case_with_context(case_id)
        if context is None:
            raise HTTPException(status_code=404, detail="support_case_not_found")
        sla = None
        if context.status not in {"closed", "cancelled"} and context.opened_at:
            db_now = repository.database_now()
            waiting_seconds = repository.get_case_waiting_seconds(case_id, db_now)
            sla = _sla_to_response(
                compute_sla(
                    context.priority,
                    context.opened_at,
                    context.status,
                    db_now,
                    settings,
                    waiting_seconds=waiting_seconds,
                ),
            )
        events = repository.get_case_events(case_id)
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_console_case_viewed",
        request_id=request_id,
        case_id=context.case_id,
        status=context.status,
        turn_count=context.turn_count,
    )
    return ConsoleCaseDetailResponse(
        **_context_to_response(request_id, context).model_dump(),
        sla=sla,
        assignee=_assignee_from_context(context),
        events=[
            ConsoleCaseEventResponse(
                action=event.action,
                from_status=event.from_status,
                to_status=event.to_status,
                note=event.note,
                actor_kind=event.actor_kind,
                actor_display_name=event.actor_display_name,
                created_at=event.created_at,
            )
            for event in events
        ],
    )


@router.post(
    "/cases/{case_id}/transition",
    response_model=StaffTransitionResponse,
)
def transition_console_case(
    case_id: str,
    payload: StaffTransitionRequest,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> StaffTransitionResponse:
    _require_csrf_header(request)
    service = SupportCaseTransitionService(request.app.state.database_runtime)
    try:
        result = service.apply(
            case_id=case_id,
            action=payload.action,
            actor_staff_id=principal.staff_id,
            note=payload.note,
        )
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail="support_case_not_found") from exc
    except InvalidTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_transition", "status": exc.status},
        ) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    log_event(
        logger,
        "support_console_transition",
        request_id=get_request_id(request),
        case_id=result.case_id,
        action=payload.action,
        from_status=result.from_status,
        to_status=result.to_status,
        actor_staff_id=principal.staff_id,
    )
    return StaffTransitionResponse(
        case_id=result.case_id,
        status=result.to_status,
        assignee=(
            ConsoleAssigneeResponse(display_name=result.assignee_display_name)
            if result.assignee_display_name
            else None
        ),
    )


@router.post(
    "/cases/{case_id}/message",
    response_model=ConsoleCaseMessageResponse,
)
def send_console_case_message(
    case_id: str,
    payload: ConsoleCaseMessageRequest,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseMessageResponse:
    """Ponte WhatsApp<->console: o atendente responde o cliente pelo caso.

    So funciona dentro da janela de 24h da Meta (free-form); fora da janela,
    responde 409 -- enviar template fica para a Fase 2. Dark quando
    ``ENABLE_WHATSAPP_SUPPORT_NUMBER`` esta desligada.
    """

    _require_csrf_header(request)
    settings = request.app.state.settings
    if not settings.enable_whatsapp_support_number:
        raise HTTPException(status_code=404, detail="Not found")

    runtime = _get_runtime(request)
    try:
        runtime.reply_limiter.check(case_id)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    bridge = SupportWhatsAppBridgeService(
        settings=settings,
        database_runtime=request.app.state.database_runtime,
        client=MetaWhatsAppClient(
            access_token=settings.meta_whatsapp_access_token or "",
            phone_number_id=settings.meta_support_phone_number_id or "",
            graph_api_version=settings.meta_whatsapp_graph_api_version,
            timeout_seconds=settings.meta_whatsapp_request_timeout_seconds,
        ),
    )
    try:
        result = bridge.send_agent_reply(
            case_id=case_id,
            staff_id=principal.staff_id,
            text=payload.message,
        )
    except CaseHasNoBinding as exc:
        raise HTTPException(
            status_code=409, detail={"code": "no_whatsapp_binding"}
        ) from exc
    except SupportWhatsAppWindowClosed as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "window_closed", "templates": []},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="empty_message") from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    log_event(
        logger,
        "support_wa_agent_message",
        request_id=get_request_id(request),
        case_id=case_id,
        staff_id=principal.staff_id,
        delivery="freeform",
    )
    return ConsoleCaseMessageResponse(message_id=result.message_id, status="queued")


@router.get("/metrics", response_model=ConsoleMetricsResponse)
def get_console_metrics(
    request: Request,
    window: str = Query(default="14d", max_length=5),
    domain: str | None = Query(default=None, max_length=80),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleMetricsResponse:
    if window not in WINDOW_DAYS:
        raise HTTPException(status_code=422, detail="invalid_window")

    settings = request.app.state.settings
    database_runtime = request.app.state.database_runtime
    case_repository = SupportCaseRepository(database_runtime)
    metrics_repository = SupportMetricsRepository(database_runtime)
    try:
        now = case_repository.database_now()
        metrics = build_console_metrics(
            case_repository=case_repository,
            metrics_repository=metrics_repository,
            window=window,
            domain=domain,
            settings=settings,
            now=now,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_console_metrics_viewed",
        request_id=request_id,
        window=window,
        domain_present=domain is not None,
    )
    return ConsoleMetricsResponse(
        request_id=request_id,
        window=window,
        domain=domain,
        **metrics,
    )


def _assess(case: SupportCaseSummary, db_now: object, settings: object) -> SlaAssessment:
    return compute_sla(
        case.priority,
        case.opened_at,
        case.status,
        db_now,
        settings,
        waiting_seconds=case.waiting_seconds,
    )


def _sla_to_response(sla: SlaAssessment) -> ConsoleSlaResponse:
    return ConsoleSlaResponse(
        deadline_at=sla.deadline_at,
        elapsed_ratio=sla.elapsed_ratio,
        color=sla.color,
        paused=sla.paused,
        explanation=sla.explanation,
    )


def _assignee_from_summary(case: SupportCaseSummary) -> ConsoleAssigneeResponse | None:
    if not case.assignee_display_name:
        return None
    return ConsoleAssigneeResponse(display_name=case.assignee_display_name)


def _assignee_from_context(context) -> ConsoleAssigneeResponse | None:
    if not context.assignee_display_name:
        return None
    return ConsoleAssigneeResponse(display_name=context.assignee_display_name)
