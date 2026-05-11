from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    domain: str | None = None


class ChatResponse(BaseModel):
    request_id: str
    domain: str
    answer: str
    confidence: float
    escalated: bool
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str]
    error_code: str | None = None
