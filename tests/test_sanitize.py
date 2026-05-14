import pytest

from app.core.sanitize import MAX_INPUT_LENGTH, sanitize_user_input


def test_sanitize_user_input_trims_and_removes_control_chars() -> None:
    raw = "  oi\x00mundo\x1F  "

    sanitized = sanitize_user_input(raw)

    assert sanitized == "oimundo"


def test_sanitize_user_input_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="message too long"):
        sanitize_user_input("x" * (MAX_INPUT_LENGTH + 1))
