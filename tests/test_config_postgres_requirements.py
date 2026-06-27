import pytest

from app.core.config import Settings


def test_pgvector_requires_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            RETRIEVAL_BACKEND="pgvector",
            DATABASE_URL="",
        )


def test_unknown_retrieval_backend_is_rejected_at_configuration_time() -> None:
    with pytest.raises(ValueError, match="RETRIEVAL_BACKEND"):
        Settings(
            _env_file=None,
            APP_ENV="development",
            RETRIEVAL_BACKEND="unknown",
        )


def test_generic_verified_delivery_url_is_used_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        VERIFIED_HANDOFF_WEBHOOK_URL="https://delivery.internal/handoff",
    )

    assert settings.verified_handoff_webhook_url == "https://delivery.internal/handoff"
