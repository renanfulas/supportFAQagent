from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit


REDACTION_VERSION = "phase0-v1"
REDACTED_SECRET = "[REDACTED_SECRET]"
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_CANDIDATE = re.compile(
    r"(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_GITHUB_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
)
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_STRIPE_SECRET_KEY = re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")
_GOOGLE_API_KEY = re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_BASIC_AUTH = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{8,}")
_SECRET_LABEL = (
    r"secret[\s_-]?access[\s_-]?key|access[\s_-]?key(?:[\s_-]?id)?|"
    r"password|passwd|pwd|senha|passphrase|token|access[\s_-]?token|"
    r"refresh[\s_-]?token|api[\s_-]?key|client[\s_-]?secret|"
    r"private[\s_-]?key|secret|segredo|credential|credentials|"
    r"credencial|credenciais|cookie|cookies|authorization"
)
_SECRET_VALUE = r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)"""
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)* PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_PREFIXED_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<label>[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*[_-]"
    rf"(?:secret[_-]?access[_-]?key|access[_-]?key(?:[_-]?id)?|"
    rf"password|passwd|pwd|token|api[_-]?key|secret|cookie|authorization))"
    rf"\s*[:=]\s*(?P<value>{_SECRET_VALUE})"
)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<label>{_SECRET_LABEL})\s*[:=]\s*(?P<value>{_SECRET_VALUE})"
)
_NATURAL_LANGUAGE_SECRET = re.compile(
    rf"(?i)\b(?P<label>(?:(?:my|the|minha|meu|a|o)\s+)?"
    rf"(?:password|senha|passphrase|secret|segredo|api[\s_-]?key|"
    rf"client[\s_-]?secret|access[\s_-]?token|refresh[\s_-]?token)"
    rf"(?:\s+(?:do|da|de|para|for)\s+[a-z0-9_.-]{{1,64}})?)"
    rf"\s+(?P<link>is|was|foi|seria|e|\u00e9)\s+"
    rf"(?P<value>[^\r\n,;.!?]+)"
)
_SENSITIVE_HEADER = re.compile(
    r"(?im)^(?P<name>[ \t]*(?:authorization|proxy-authorization|cookie|"
    r"set-cookie|x-api-key|x-auth-token|x-access-token|api-key|apikey)"
    r"[ \t]*:)[^\r\n]*"
)
_QUOTED_SENSITIVE_FIELD = re.compile(
    rf"""(?i)(?P<key>["'](?:authorization|proxy-authorization|cookie|"""
    rf"""set-cookie|x-api-key|x-auth-token|x-access-token|api-key|apikey|"""
    rf"""password|passwd|pwd|senha|token|secret)["']\s*:\s*)"""
    rf"""(?P<value>{_SECRET_VALUE})"""
)
_SENSITIVE_COOKIE_PAIR = re.compile(
    r"(?i)\b(?P<name>session(?:id)?|connect\.sid|csrf(?:token)?|xsrf-token|"
    r"auth(?:_token)?|access_token|refresh_token|jwt)\s*=\s*[^;\s,]+"
)
_URI = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>'\"]+", re.IGNORECASE)
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "code",
    "credential",
    "credentials",
    "key",
    "password",
    "passwd",
    "pwd",
    "refresh_token",
    "secret",
    "senha",
    "signature",
    "token",
}
_SENSITIVE_PAYLOAD_KEYS = _SENSITIVE_QUERY_KEYS | {
    "cookie",
    "cookies",
    "private_key",
    "proxy_authorization",
    "set_cookie",
    "x_access_token",
    "x_api_key",
    "x_auth_token",
}
_SENSITIVE_PATH_SEGMENTS = {
    "access_token",
    "api_key",
    "credential",
    "credentials",
    "key",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "senha",
    "token",
}
_TRAILING_URI_PUNCTUATION = ".,;:!?)]}>"


def sanitize_for_persistence(text: str | None) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        raise TypeError("persisted text must be a string")
    value = _PRIVATE_KEY_BLOCK.sub(REDACTED_SECRET, text)
    value = _SENSITIVE_HEADER.sub(
        lambda match: f"{match.group('name')} {REDACTED_SECRET}",
        value,
    )
    value = _QUOTED_SENSITIVE_FIELD.sub(
        lambda match: f"{match.group('key')}{REDACTED_SECRET}",
        value,
    )
    value = _SENSITIVE_COOKIE_PAIR.sub(
        lambda match: f"{match.group('name')}={REDACTED_SECRET}",
        value,
    )
    value = _URI.sub(_sanitize_uri, value)
    value = _OPENAI_KEY.sub(REDACTED_SECRET, value)
    value = _GITHUB_TOKEN.sub(REDACTED_SECRET, value)
    value = _AWS_ACCESS_KEY.sub(REDACTED_SECRET, value)
    value = _SLACK_TOKEN.sub(REDACTED_SECRET, value)
    value = _STRIPE_SECRET_KEY.sub(REDACTED_SECRET, value)
    value = _GOOGLE_API_KEY.sub(REDACTED_SECRET, value)
    value = _JWT.sub(REDACTED_SECRET, value)
    value = _BEARER.sub("Bearer [REDACTED_SECRET]", value)
    value = _BASIC_AUTH.sub("Basic [REDACTED_SECRET]", value)
    value = _PREFIXED_SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('label')}={REDACTED_SECRET}",
        value,
    )
    value = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('label')}={REDACTED_SECRET}",
        value,
    )
    value = _NATURAL_LANGUAGE_SECRET.sub(
        lambda match: (
            f"{match.group('label')} {match.group('link')} {REDACTED_SECRET}"
        ),
        value,
    )
    value = _EMAIL.sub("[REDACTED_EMAIL]", value)
    value = _IPV4.sub("[REDACTED_IP]", value)
    value = _IPV6_CANDIDATE.sub(_sanitize_ipv6, value)
    value = _PHONE.sub("[REDACTED_PHONE]", value)
    return value


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_for_persistence(value)
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            rendered_key = str(key)
            if _normalize_sensitive_key(rendered_key) in _SENSITIVE_PAYLOAD_KEYS:
                sanitized[rendered_key] = REDACTED_SECRET
            else:
                sanitized[rendered_key] = sanitize_payload(item)
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported persisted payload type: {type(value).__name__}")


def _sanitize_uri(match: re.Match[str]) -> str:
    raw = match.group(0)
    candidate = raw.rstrip(_TRAILING_URI_PUNCTUATION)
    trailing = raw[len(candidate) :]
    try:
        parts = urlsplit(candidate)
        query_keys = {
            _normalize_sensitive_key(key)
            for key, _ in parse_qsl(parts.query, keep_blank_values=True)
        }
        path_segments = {
            _normalize_sensitive_key(segment)
            for segment in parts.path.split("/")
            if segment
        }
        path_is_sensitive = bool(
            path_segments.intersection(_SENSITIVE_PATH_SEGMENTS)
        )
        if not (
            parts.username
            or parts.password
            or query_keys.intersection(_SENSITIVE_QUERY_KEYS)
            or path_is_sensitive
        ):
            return candidate + trailing

        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{host}{port}"
        return (
            urlunsplit((parts.scheme, netloc, "/[REDACTED_URL]", "", ""))
            + trailing
        )
    except ValueError:
        return "[REDACTED_URL]"


def _normalize_sensitive_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _sanitize_ipv6(match: re.Match[str]) -> str:
    candidate = match.group(0)
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    return "[REDACTED_IP]" if parsed.version == 6 else candidate
