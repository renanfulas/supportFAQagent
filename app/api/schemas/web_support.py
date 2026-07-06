"""Contratos HTTP da fachada web staff (/web/support/*).

O bloco de caso reusa os contratos do inbox interno (mesma fonte de dados) e
acrescenta os blocos ``sla`` e ``assignee`` do console.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.support import (
    SupportCaseDetailResponse,
    SupportCaseSummaryResponse,
)


class StaffOtpStartRequest(BaseModel):
    # Opcional quando o cookie de lembrete do dispositivo esta presente.
    phone: str | None = Field(default=None, max_length=20)


class StaffOtpStartResponse(BaseModel):
    challenge_id: str
    expires_in_seconds: int
    retry_after_seconds: int


class StaffOtpConfirmRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=4, max_length=10)
    # Reenviado pela tela de login no primeiro acesso para vincular o lembrete
    # de dispositivo; nunca persistido em claro.
    phone: str | None = Field(default=None, max_length=20)


class StaffLoginResponse(BaseModel):
    display_name: str
    expires_at: datetime


class StaffSessionResponse(BaseModel):
    authenticated: bool = True
    display_name: str
    expires_at: datetime


class StaffLogoutRequest(BaseModel):
    forget_device: bool = False


class StaffLogoutResponse(BaseModel):
    authenticated: bool = False


class ConsoleSlaResponse(BaseModel):
    deadline_at: datetime
    elapsed_ratio: float
    color: str
    paused: bool
    explanation: str


class ConsoleAssigneeResponse(BaseModel):
    display_name: str


class ConsoleCaseSummaryResponse(SupportCaseSummaryResponse):
    # ``sla`` e null no historico (fechados/cancelados nao passam por SLA).
    sla: ConsoleSlaResponse | None = None
    assignee: ConsoleAssigneeResponse | None = None


class ConsoleCaseListResponse(BaseModel):
    request_id: str | None = None
    view: str
    count: int
    limit: int
    offset: int
    truncated: bool = False
    cases: list[ConsoleCaseSummaryResponse] = Field(default_factory=list)


class ConsoleCaseEventResponse(BaseModel):
    action: str
    from_status: str
    to_status: str
    note: str | None = None
    actor_kind: str = "staff"
    actor_display_name: str
    created_at: datetime


class ConsoleCaseDetailResponse(SupportCaseDetailResponse):
    sla: ConsoleSlaResponse | None = None
    assignee: ConsoleAssigneeResponse | None = None
    events: list[ConsoleCaseEventResponse] = Field(default_factory=list)


class StaffTransitionRequest(BaseModel):
    action: Literal[
        "claim", "release", "wait_customer", "resume", "close", "cancel"
    ]
    note: str | None = Field(default=None, max_length=1000)


class StaffTransitionResponse(BaseModel):
    case_id: str
    status: str
    assignee: ConsoleAssigneeResponse | None = None


class ConsoleCaseMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConsoleCaseMessageResponse(BaseModel):
    message_id: str
    status: str = "queued"


class MetricsBacklogResponse(BaseModel):
    by_color: dict[str, int]
    by_status: dict[str, int]
    truncated: bool = False


class MetricsThroughputEntry(BaseModel):
    day: str
    opened: int
    closed: int


class MetricsEscalationReasonEntry(BaseModel):
    reason_code: str
    count: int


class MetricsFeedbackResponse(BaseModel):
    helpful: int
    not_helpful: int
    helpful_rate: float | None = None
    unknown_domain_count: int
    sample_note: str | None = None


class MetricsResponseTimesResponse(BaseModel):
    median_seconds_to_first_action: float | None = None
    median_seconds_to_close: float | None = None


class ConsoleMetricsResponse(BaseModel):
    request_id: str | None = None
    window: str
    domain: str | None = None
    backlog: MetricsBacklogResponse
    throughput: list[MetricsThroughputEntry] = Field(default_factory=list)
    escalation_reasons: list[MetricsEscalationReasonEntry] = Field(default_factory=list)
    feedback: MetricsFeedbackResponse
    response_times: MetricsResponseTimesResponse
