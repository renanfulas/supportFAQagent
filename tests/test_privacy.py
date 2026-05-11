from app.core.privacy import hash_sensitive_value


def test_hash_sensitive_value_is_stable_and_masks_raw_value() -> None:
    value = "whatsapp:+5511999999999"

    hashed = hash_sensitive_value(value)

    assert hashed == hash_sensitive_value(f" {value} ")
    assert hashed != value
    assert len(hashed or "") == 16


def test_hash_sensitive_value_handles_blank_values() -> None:
    assert hash_sensitive_value(None) is None
    assert hash_sensitive_value("   ") is None
