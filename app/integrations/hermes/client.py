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
class HermesClient:
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
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}{self.otp_delivery_path}",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Delivery-ID": delivery_id,
                    "X-Webhook-Timestamp": timestamp,
                    "X-Webhook-Signature": f"sha256={signature}",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise HermesRequestError("hermes_request_failed", status_code=status_code) from exc
