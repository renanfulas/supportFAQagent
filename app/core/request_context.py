import re
from uuid import uuid4

from fastapi import Request


REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_LENGTH = 80
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_SENSITIVE_REQUEST_ID_PREFIXES = (
    "api-key",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "ghp_",
    "github_pat_",
    "password",
    "secret",
    "senha",
    "sk-",
    "token",
)


def resolve_request_id(raw_request_id: str | None) -> str:
    if raw_request_id is None:
        return str(uuid4())

    request_id = raw_request_id.strip()
    normalized = request_id.lower()
    if (
        not request_id
        or len(request_id) > MAX_REQUEST_ID_LENGTH
        or _SAFE_REQUEST_ID.fullmatch(request_id) is None
        or normalized.startswith(_SENSITIVE_REQUEST_ID_PREFIXES)
    ):
        return str(uuid4())

    return request_id


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id

    return str(uuid4())
