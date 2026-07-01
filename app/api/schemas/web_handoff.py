from pydantic import BaseModel, ConfigDict, Field


class HandoffConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)


class HandoffConsentResponse(BaseModel):
    support_case_id: str
    status: str
    opened_at: str
    summary: str | None = None
    domain: str
