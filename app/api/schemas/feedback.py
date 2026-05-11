from pydantic import BaseModel, Field, field_validator


class FeedbackRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=80)
    session_id: str | None = Field(default=None, max_length=160)
    message_id: str | None = Field(default=None, max_length=80)
    helpful: bool
    reason: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="api", min_length=1, max_length=60)

    @field_validator(
        "request_id",
        "session_id",
        "message_id",
        "reason",
        "comment",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        return normalized or None

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source cannot be blank")
        return normalized


class FeedbackResponse(BaseModel):
    feedback_id: str
    accepted: bool
    status: str
    storage: str
