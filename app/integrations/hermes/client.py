from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any

import requests


class HermesConfigurationError(RuntimeError):
    pass


class HermesRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class HermesSendResult:
    message_id: str


@dataclass(frozen=True)
class HermesClient:
    """OTP delivery client (signed POST to the Hermes gateway)."""

    base_url: str
    webhook_secret: str
    timeout_seconds: int = 5
    otp_delivery_path: str = "/otp-delivery"

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise HermesConfigurationError("HERMES_BASE_URL is required")
        if not self.webhook_secret.strip():
            raise HermesConfigurationError("HERMES_WEBHOOK_SECRET is required")
        if not self.otp_delivery_path.strip().startswith("/"):
            raise HermesConfigurationError("HERMES_OTP_DELIVERY_PATH must start with /")

    def deliver_otp(self, payload: dict[str, Any], *, delivery_id: str) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}{self.otp_delivery_path}",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Delivery-ID": delivery_id,
                    "X-Webhook-Timestamp": timestamp,
                    "X-Webhook-Signature": signature,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise HermesRequestError("hermes_request_failed", status_code=status_code) from exc


@dataclass(frozen=True)
class HermesBridgeClient:
    """Outbound chat sender for the WhatsApp bridge.

    Real contract of the bridge: ``POST {base_url}/send {"chatId", "message"}`` on a
    localhost express server (no HMAC). Returns the provider message id when present.
    """

    base_url: str = "http://127.0.0.1:3000"
    timeout_seconds: int = 10
    send_path: str = "/send"

    def send_text(self, *, to: str, text: str, message_id: str) -> HermesSendResult:
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}{self.send_path}",
                json={"chatId": to, "message": text},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise HermesRequestError("hermes_bridge_send_failed", status_code=status_code) from exc

        provider_id = message_id
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("messageId"):
                provider_id = str(data["messageId"])
        except ValueError:
            pass
        return HermesSendResult(message_id=provider_id)
