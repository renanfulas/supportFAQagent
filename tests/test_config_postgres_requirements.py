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


def test_legacy_n8n_verified_url_remains_supported_temporarily() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        N8N_VERIFIED_HANDOFF_URL="https://n8n.internal/handoff",
    )

    assert settings.verified_handoff_webhook_url == "https://n8n.internal/handoff"


def test_generic_verified_delivery_url_precedes_matching_legacy_alias() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        VERIFIED_HANDOFF_WEBHOOK_URL="https://delivery.internal/handoff",
        N8N_VERIFIED_HANDOFF_URL="https://n8n.internal/handoff",
    )

    assert settings.verified_handoff_webhook_url == "https://delivery.internal/handoff"


def test_conflicting_generic_and_legacy_delivery_urls_fail_outside_local() -> None:
    with pytest.raises(ValueError, match="conflicts with legacy"):
        Settings(
            _env_file=None,
            APP_ENV="staging",
            API_SECRET_KEY="staging-test-secret",
            VERIFIED_HANDOFF_WEBHOOK_URL="https://delivery.internal/handoff",
            N8N_VERIFIED_HANDOFF_URL="https://n8n.internal/handoff",
        )
