from hashlib import sha256


def hash_sensitive_value(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return sha256(normalized.encode("utf-8")).hexdigest()[:16]
