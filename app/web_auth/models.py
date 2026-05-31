from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OtpChallenge:
    id: str
    phone_hash: str
    phone_last4: str
    code_digest: str
    created_at: datetime
    expires_at: datetime
    attempts_remaining: int
    status: str = "pending"


@dataclass
class VerifiedIdentity:
    id: str
    phone_hash: str
    phone_last4: str
    verified_at: datetime
    status: str = "verified"


@dataclass(frozen=True)
class OtpDeliveryRequest:
    challenge_id: str
    phone: str
    code: str
    expires_in_seconds: int
