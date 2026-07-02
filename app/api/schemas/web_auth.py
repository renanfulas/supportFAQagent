from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppOtpStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32)


class WhatsAppOtpStartResponse(BaseModel):
    challenge_id: str
    status: Literal["pending"] = "pending"
    expires_in_seconds: int
    retry_after_seconds: int
    # Sprint 4b: hint for the widget to show a client-side "still there?" nudge
    # (reusing this same start endpoint to resend) -- there is no server-side
    # reminder job, since the raw phone is never persisted long enough for one
    # to know who to re-contact.
    abandonment_reminder_seconds: int


class WhatsAppOtpConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=1, max_length=80)
    code: str = Field(pattern=r"^\d{6}$")


class VerifiedSessionResponse(BaseModel):
    status: Literal["verified"] = "verified"
    phone_last4: str


class AnonymousSessionResponse(BaseModel):
    status: Literal["anonymous"] = "anonymous"
