from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


REDACTION_VERSION = "phase0-v1"
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|senha|token|api[_-]?key|secret|cookie|authorization)\s*[:=]\s*([^\s,;]+)"
)
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def sanitize_for_persistence(text: str | None) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        raise TypeError("persisted text must be a string")
    value = _URL.sub(_sanitize_url, text)
    value = _OPENAI_KEY.sub("[REDACTED_SECRET]", value)
    value = _BEARER.sub("Bearer [REDACTED_SECRET]", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED_SECRET]", value)
    value = _EMAIL.sub("[REDACTED_EMAIL]", value)
    value = _IPV4.sub("[REDACTED_IP]", value)
    value = _IPV6.sub("[REDACTED_IP]", value)
    value = _PHONE.sub("[REDACTED_PHONE]", value)
    return value


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_for_persistence(value)
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_payload(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported persisted payload type: {type(value).__name__}")


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{host}{port}"
        if parts.username or parts.password or parts.query:
            return urlunsplit((parts.scheme, netloc, "/[REDACTED_URL]", "", ""))
        if any(marker in parts.path.lower() for marker in ("token", "secret", "key", "password")):
            return urlunsplit((parts.scheme, netloc, "/[REDACTED_URL]", "", ""))
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "[REDACTED_URL]"
