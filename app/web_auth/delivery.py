from __future__ import annotations

from typing import Protocol

from app.web_auth.models import OtpDeliveryRequest


class OtpDeliveryUnavailable(Exception):
    pass


class OtpDeliveryAdapter(Protocol):
    def deliver(self, request: OtpDeliveryRequest) -> None: ...


class InMemoryOtpDeliveryAdapter:
    """Captures OTP deliveries for private local tests only."""

    def __init__(self) -> None:
        self.requests: list[OtpDeliveryRequest] = []

    def deliver(self, request: OtpDeliveryRequest) -> None:
        self.requests.append(request)
