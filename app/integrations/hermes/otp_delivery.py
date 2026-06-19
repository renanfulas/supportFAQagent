from __future__ import annotations

from math import ceil

from app.integrations.hermes.client import HermesClient, HermesRequestError
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.models import OtpDeliveryRequest


class HermesOtpDeliveryAdapter:
    def __init__(self, *, client: HermesClient, template_name: str) -> None:
        self.client = client
        self.template_name = template_name.strip() or "web_login_otp"

    def deliver(self, request: OtpDeliveryRequest) -> None:
        payload = {
            "delivery_id": request.challenge_id,
            "channel": "whatsapp",
            "phone_e164": request.phone,
            "template": self.template_name,
            "variables": {
                "code": request.code,
                "expires_in_minutes": ceil(request.expires_in_seconds / 60),
            },
        }
        try:
            self.client.deliver_otp(payload, delivery_id=request.challenge_id)
        except HermesRequestError as exc:
            raise OtpDeliveryUnavailable("hermes_delivery_failed") from exc
