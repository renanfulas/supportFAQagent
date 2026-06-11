from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings


API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


def is_valid_secret(candidate: str | None, expected: str | None) -> bool:
    return bool(candidate and expected) and hmac.compare_digest(
        candidate,
        expected,
    )


def is_valid_api_key(api_key: str | None) -> bool:
    return is_valid_secret(api_key, get_settings().api_secret_key)


def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> str:
    expected = request.app.state.settings.api_secret_key
    if not is_valid_secret(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return api_key
