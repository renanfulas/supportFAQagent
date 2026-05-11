from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    domain: str | None = None


class ChatResponse(BaseModel):
    domain: str
    answer: str
    confidence: float
    escalated: bool
    references: list[str]
