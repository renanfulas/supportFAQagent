"""Input hygiene helpers.

This module normalizes user-provided text for size and formatting only.
It is intentionally not the main defense against prompt injection or scope
escape. Those protections live in the domain contract, system prompt and
handoff policy.
"""

from __future__ import annotations

import re


MAX_INPUT_LENGTH = 2000
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")


def sanitize_user_input(text: str, *, max_length: int = MAX_INPUT_LENGTH) -> str:
    """Apply input hygiene without making security decisions.

    The goal is to keep transport and prompt formatting predictable:
    - trim leading/trailing whitespace
    - remove control characters that add noise
    - reject oversized payloads

    This function must not be treated as the primary prompt-injection defense.
    """

    if len(text) > max_length:
        raise ValueError(f"message too long; max {max_length} characters")

    sanitized = _CONTROL_CHARS_RE.sub("", text).strip()
    return sanitized
