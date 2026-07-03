"""Contratos HTTP da fachada web staff (/web/support/*).

O bloco de caso reusa os contratos do inbox interno (mesma fonte de dados) e
acrescenta os blocos ``sla`` e ``assignee`` do console. ``assignee`` fica
``null`` ate a Fase B.
"""

from __future__ import annotations

from datetime import datetime

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


class ConsoleCaseDetailResponse(SupportCaseDetailResponse):
    sla: ConsoleSlaResponse | None = None
    assignee: ConsoleAssigneeResponse | None = None
