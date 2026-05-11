from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    request_id: str | None = None
    session_id: str | None = None
    message_id: str | None = None
    helpful: bool
    reason: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="api", max_length=60)


class FeedbackResponse(BaseModel):
    feedback_id: str
    accepted: bool
    status: str
    storage: str
