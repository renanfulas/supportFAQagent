from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.feedback import safe_feedback_identifier
from app.core.sanitize import sanitize_user_input


class WebChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = sanitize_user_input(value, max_length=4000)
        if not normalized:
            raise ValueError("message cannot be blank")
        return normalized


class WebChatResponse(BaseModel):
    request_id: str
    answer: str
    escalated: bool
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    support_code: str
    error_code: str | None = None


class WebFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(max_length=80)
    helpful: bool
    reason: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = safe_feedback_identifier(value, field_name="request_id")
        if normalized is None:
            raise ValueError("request_id cannot be blank")
        return normalized

    @field_validator("reason", "comment", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        return normalized or None
