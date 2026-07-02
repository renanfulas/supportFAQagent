from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SupportCaseSummaryResponse(BaseModel):
    case_id: str
    domain: str
    status: str
    priority: str
    channel: str
    request_id: str
    reason_codes: list[str] = Field(default_factory=list)
    summary: str | None = None
    turn_count: int | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None


class SupportCaseListResponse(BaseModel):
    request_id: str | None = None
    count: int
    limit: int
    offset: int
    cases: list[SupportCaseSummaryResponse] = Field(default_factory=list)


class SupportCaseTranscriptTurn(BaseModel):
    sequence: int
    role: str
    content: str
    confidence: float | None = None
    escalated: bool = False
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime | None = None


class SupportCaseCustomerResponse(BaseModel):
    """Contact the customer authorized for direct follow-up (LGPD consent).

    Served only on this authenticated internal surface; the e-mail is readable
    on purpose because the team uses it for real contact.
    """

    display_label: str | None = None
    email: str | None = None
    phone_last4: str | None = None


class SupportCaseDetailResponse(BaseModel):
    request_id: str | None = None
    case_id: str
    domain: str
    status: str
    priority: str
    channel: str
    case_request_id: str
    reason_codes: list[str] = Field(default_factory=list)
    summary: str | None = None
    references: list[str] = Field(default_factory=list)
    turn_count: int
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    customer: SupportCaseCustomerResponse | None = None
    transcript: list[SupportCaseTranscriptTurn] = Field(default_factory=list)
