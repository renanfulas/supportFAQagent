import hmac
import os
import secrets
from hashlib import sha256


_EPHEMERAL_LOG_HASH_SECRET = secrets.token_bytes(32)


def hash_sensitive_value(
    value: str | None,
    *,
    secret: str | None = None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    effective_secret = secret or os.getenv("PERSISTENCE_HASH_SECRET")
    if not effective_secret:
        try:
            from app.core.config import get_settings

            effective_secret = get_settings().persistence_hash_secret
        except Exception:
            effective_secret = None
    key = (
        effective_secret.strip().encode("utf-8")
        if effective_secret and effective_secret.strip()
        else _EPHEMERAL_LOG_HASH_SECRET
    )
    return hmac.new(
        key,
        normalized.encode("utf-8"),
        sha256,
    ).hexdigest()[:16]
