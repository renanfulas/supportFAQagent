import ipaddress
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator

FeedbackSource = Literal["web", "api", "n8n", "integration", "other"]
_ALLOWED_FEEDBACK_SOURCES = frozenset({"web", "api", "n8n", "integration"})
_LIST_ITEM_MAX_LENGTHS = {
    "handoff_reasons": 80,
    "references": 500,
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_SENSITIVE_IDENTIFIER_PREFIXES = (
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "eyj",
    "ghp_",
    "github_pat_",
    "akia",
    "asia",
    "aiza",
    "password",
    "rk_live_",
    "rk_",
    "secret",
    "senha",
    "sk-",
    "sk_live_",
    "sk_",
    "token",
    "xox",
)


def safe_feedback_source(value: object) -> FeedbackSource:
    if not isinstance(value, str):
        return "other"
    normalized = value.strip().lower()
    if normalized in _ALLOWED_FEEDBACK_SOURCES:
        return normalized
    return "other"


def safe_feedback_identifier(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if (
        _SAFE_IDENTIFIER.fullmatch(normalized) is None
        or lowered.startswith(_SENSITIVE_IDENTIFIER_PREFIXES)
        or (normalized.isdigit() and len(normalized) >= 8)
        or _looks_like_phone(normalized)
        or _is_ip_address(normalized)
    ):
        raise ValueError(f"{field_name} must use a safe correlation identifier")
    return normalized


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _looks_like_phone(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        pass
    else:
        return False
    if re.search(r"\d{10,}", value):
        return True
    if re.fullmatch(r"[0-9.:-]+", value) is None:
        return False
    return len(re.sub(r"\D", "", value)) >= 10


class FeedbackRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=80)
    session_id: str | None = Field(default=None, max_length=160)
    message_id: str | None = Field(default=None, max_length=80)
    helpful: bool
    reason: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=1000)
    source: FeedbackSource = "api"
    escalated: bool | None = None
    handoff_reasons: list[str] = Field(default_factory=list, max_length=10)
    references: list[str] = Field(default_factory=list, max_length=20)
    error_code: str | None = Field(default=None, max_length=80)

    @field_validator("request_id", "message_id", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object, info: ValidationInfo) -> str | None:
        return safe_feedback_identifier(value, field_name=info.field_name)

    @field_validator("session_id", "reason", "comment", "error_code", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        return normalized or None

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("source must be a string")
        if not value.strip():
            raise ValueError("source cannot be blank")
        return safe_feedback_source(value)

    @field_validator("handoff_reasons", "references", mode="before")
    @classmethod
    def normalize_string_list(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value

        max_length = _LIST_ITEM_MAX_LENGTHS[info.field_name]
        normalized_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                normalized_items.append(item)
                continue

            normalized = item.strip()
            if normalized:
                if len(normalized) > max_length:
                    raise ValueError(
                        f"{info.field_name} items cannot exceed {max_length} characters"
                    )
                normalized_items.append(normalized)

        return normalized_items


class FeedbackResponse(BaseModel):
    feedback_id: str
    accepted: bool
    status: str
    storage: str
