import pytest

from app.api.schemas.chat import ChatRequest
from app.core.sanitize import MAX_INPUT_LENGTH, sanitize_user_input


def test_sanitize_user_input_trims_and_removes_control_chars() -> None:
    raw = "  oi\x00mundo\x1F  "

    sanitized = sanitize_user_input(raw)

    assert sanitized == "oimundo"


def test_sanitize_user_input_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="message too long"):
        sanitize_user_input("x" * (MAX_INPUT_LENGTH + 1))


def test_chat_request_applies_input_hygiene_without_reducing_public_limit() -> None:
    payload = ChatRequest(message="x" * 4000)

    assert payload.message == "x" * 4000


def test_chat_request_removes_control_characters() -> None:
    payload = ChatRequest(message="  oi\x00mundo\x1F  ")

    assert payload.message == "oimundo"
