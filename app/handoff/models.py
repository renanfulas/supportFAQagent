from pydantic import BaseModel, Field


class HandoffDecision(BaseModel):
    escalated: bool
    reasons: list[str] = Field(default_factory=list)
