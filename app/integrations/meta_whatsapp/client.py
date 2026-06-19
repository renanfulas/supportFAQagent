from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.integrations.meta_whatsapp.schemas import MetaSendResult


GRAPH_API_BASE_URL = "https://graph.facebook.com"


class MetaWhatsAppConfigurationError(RuntimeError):
    pass


class MetaWhatsAppRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MetaWhatsAppClient:
    access_token: str
    phone_number_id: str
    graph_api_version: str
    timeout_seconds: int = 5
    base_url: str = GRAPH_API_BASE_URL

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise MetaWhatsAppConfigurationError("META_WHATSAPP_ACCESS_TOKEN is required")
        if not self.phone_number_id.strip():
            raise MetaWhatsAppConfigurationError("META_WHATSAPP_PHONE_NUMBER_ID is required")
        if not self.graph_api_version.strip():
            raise MetaWhatsAppConfigurationError("META_WHATSAPP_GRAPH_API_VERSION is required")

    def send_text(self, *, to: str, text: str) -> MetaSendResult:
        if not to.strip() or not text.strip():
            raise ValueError("to and text are required")
        return self._post_message(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            }
        )

    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]] | None = None,
    ) -> MetaSendResult:
        if not to.strip() or not template_name.strip() or not language_code.strip():
            raise ValueError("to, template_name and language_code are required")
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components
        return self._post_message(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": template,
            }
        )

    def _post_message(self, payload: dict[str, Any]) -> MetaSendResult:
        url = (
            f"{self.base_url.rstrip('/')}/{self.graph_api_version.strip('/')}/"
            f"{self.phone_number_id}/messages"
        )
        try:
            response = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise MetaWhatsAppRequestError(
                "meta_whatsapp_request_failed",
                status_code=status_code,
            ) from exc
        body = response.json()
        messages = body.get("messages") if isinstance(body, dict) else None
        contacts = body.get("contacts") if isinstance(body, dict) else None
        message_id = _first_field(messages, "id")
        if message_id is None:
            raise MetaWhatsAppRequestError("meta_whatsapp_response_invalid")
        return MetaSendResult(
            message_id=message_id,
            contact_wa_id=_first_field(contacts, "wa_id"),
        )


def _first_field(items: object, field_name: str) -> str | None:
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    value = first.get(field_name)
    return value if isinstance(value, str) and value else None
