from __future__ import annotations

import hashlib
import hmac

from app.integrations.meta_whatsapp.schemas import MetaWebhookPayload, parse_webhook_payload


SIGNATURE_PREFIX = "sha256="


def verify_meta_signature(
    *,
    body: bytes,
    signature: str | None,
    app_secret: str,
) -> bool:
    if not body or not signature or not app_secret:
        return False
    if not signature.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    received = signature[len(SIGNATURE_PREFIX) :]
    return hmac.compare_digest(expected, received)


def parse_meta_webhook_payload(payload: dict[str, object]) -> MetaWebhookPayload:
    return parse_webhook_payload(payload)
