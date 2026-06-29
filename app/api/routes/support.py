"""Internal support inbox: list and inspect durable handoff tickets.

Authenticated read surface for the human support team. It exposes the
durable ``support_cases`` rows together with the assembled conversation
context. Dark by default — gated behind ``enable_support_inbox`` — and never
logs raw transcript content, only counts and identifiers safe to persist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.schemas.support import (
    SupportCaseDetailResponse,
    SupportCaseListResponse,
    SupportCaseSummaryResponse,
    SupportCaseTranscriptTurn,
)
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.core.security import verify_api_key
from app.support.context import SupportCaseContext
from app.support.repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SupportCaseRepository,
    SupportCaseSummary,
)


router = APIRouter()
logger = logging.getLogger(__name__)

_ALLOWED_STATUSES = {
    "open",
    "in_progress",
    "waiting_customer",
    "closed",
    "cancelled",
}


def _ensure_enabled(request: Request) -> None:
    if not request.app.state.settings.enable_support_inbox:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("", response_model=SupportCaseListResponse)
def list_support_cases(
    request: Request,
    domain: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(verify_api_key),
) -> SupportCaseListResponse:
    _ensure_enabled(request)
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status_filter")

    repository = SupportCaseRepository(request.app.state.database_runtime)
    try:
        cases = repository.list_cases(
            domain=domain,
            status=status,
            limit=limit,
            offset=offset,
        )
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_inbox_listed",
        request_id=request_id,
        domain_filter_present=domain is not None,
        status_filter=status,
        result_count=len(cases),
        limit=limit,
        offset=offset,
    )
    return SupportCaseListResponse(
        request_id=request_id,
        count=len(cases),
        limit=limit,
        offset=offset,
        cases=[_summary_to_response(case) for case in cases],
    )


@router.get("/{case_id}", response_model=SupportCaseDetailResponse)
def get_support_case(
    case_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
) -> SupportCaseDetailResponse:
    _ensure_enabled(request)
    repository = SupportCaseRepository(request.app.state.database_runtime)
    try:
        context = repository.get_case_with_context(case_id)
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc
    if context is None:
        raise HTTPException(status_code=404, detail="support_case_not_found")

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_inbox_case_viewed",
        request_id=request_id,
        case_id=context.case_id,
        status=context.status,
        turn_count=context.turn_count,
        reason_code_count=len(context.reason_codes),
    )
    return _context_to_response(request_id, context)


def _summary_to_response(case: SupportCaseSummary) -> SupportCaseSummaryResponse:
    return SupportCaseSummaryResponse(
        case_id=case.case_id,
        domain=case.domain,
        status=case.status,
        priority=case.priority,
        channel=case.channel,
        request_id=case.request_id,
        reason_codes=case.reason_codes,
        summary=case.summary,
        opened_at=case.opened_at,
        updated_at=case.updated_at,
    )


def _context_to_response(
    request_id: str | None,
    context: SupportCaseContext,
) -> SupportCaseDetailResponse:
    return SupportCaseDetailResponse(
        request_id=request_id,
        case_id=context.case_id,
        domain=context.domain,
        status=context.status,
        priority=context.priority,
        channel=context.channel,
        case_request_id=context.request_id,
        reason_codes=context.reason_codes,
        summary=context.summary,
        references=context.references,
        turn_count=context.turn_count,
        opened_at=context.opened_at,
        updated_at=context.updated_at,
        transcript=[
            SupportCaseTranscriptTurn(
                sequence=turn.sequence,
                role=turn.role,
                content=turn.content,
                confidence=turn.confidence,
                escalated=turn.escalated,
                handoff_reasons=turn.handoff_reasons,
                references=turn.references,
                error_code=turn.error_code,
                created_at=turn.created_at,
            )
            for turn in context.transcript
        ],
    )
