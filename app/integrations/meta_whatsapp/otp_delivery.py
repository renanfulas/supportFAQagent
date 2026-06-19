from __future__ import annotations

from math import ceil

from app.integrations.meta_whatsapp.client import MetaWhatsAppClient, MetaWhatsAppRequestError
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.models import OtpDeliveryRequest


class MetaWhatsAppOtpDeliveryAdapter:
    def __init__(
        self,
        *,
        client: MetaWhatsAppClient,
        template_name: str,
        language_code: str,
    ) -> None:
        self.client = client
        self.template_name = template_name.strip()
        self.language_code = language_code.strip()
        if not self.template_name:
            raise ValueError("template_name is required")
        if not self.language_code:
            raise ValueError("language_code is required")

    def deliver(self, request: OtpDeliveryRequest) -> None:
        try:
            self.client.send_template(
                to=request.phone,
                template_name=self.template_name,
                language_code=self.language_code,
                components=[
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": request.code},
                            {
                                "type": "text",
                                "text": str(ceil(request.expires_in_seconds / 60)),
                            },
                        ],
                    }
                ],
            )
        except (MetaWhatsAppRequestError, ValueError) as exc:
            raise OtpDeliveryUnavailable("meta_whatsapp_delivery_failed") from exc
