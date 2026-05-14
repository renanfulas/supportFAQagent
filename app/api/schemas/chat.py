from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sanitize import sanitize_user_input


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=160)
    domain: str | None = Field(default=None, max_length=80)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = sanitize_user_input(value, max_length=4000)
        if not normalized:
            raise ValueError("message cannot be blank")
        return normalized

    @field_validator("session_id", "domain")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None


class ChatResponse(BaseModel):
    request_id: str
    domain: str
    answer: str
    confidence: float
    escalated: bool
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str]
    error_code: str | None = None
