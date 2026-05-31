from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request, Response

from app.core.config import Settings


PUBLIC_SESSION_PREFIX = "web:"
PUBLIC_SESSION_COOKIE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def get_or_create_public_session_id(
    request: Request,
    settings: Settings,
) -> tuple[str, bool]:
    return ensure_public_session_id(
        request.cookies.get(settings.web_chat_session_cookie),
    )


def ensure_public_session_id(raw_session_id: str | None) -> tuple[str, bool]:
    normalized = raw_session_id.strip() if raw_session_id else None
    if is_valid_public_session_id(normalized):
        return normalized, False

    return build_public_session_id(), True


def build_public_session_id() -> str:
    return f"{PUBLIC_SESSION_PREFIX}{uuid4()}"


def is_valid_public_session_id(session_id: str | None) -> bool:
    if not session_id or not session_id.startswith(PUBLIC_SESSION_PREFIX):
        return False

    try:
        UUID(session_id[len(PUBLIC_SESSION_PREFIX) :])
    except ValueError:
        return False

    return True


def extract_public_session_token(session_id: str | None) -> str | None:
    if not is_valid_public_session_id(session_id):
        return None

    return session_id[len(PUBLIC_SESSION_PREFIX) :]


def set_public_session_cookie(
    response: Response,
    settings: Settings,
    session_id: str,
) -> None:
    response.set_cookie(
        key=settings.web_chat_session_cookie,
        value=session_id,
        max_age=PUBLIC_SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=bool(settings.web_chat_cookie_secure),
    )
