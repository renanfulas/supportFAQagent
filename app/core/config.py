from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_ENVS = {"development", "dev", "local"}
LOCAL_DEV_API_KEY = "local-dev-api-key"


class Settings(BaseSettings):
    app_name: str = Field(default="supportFAQagent", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    default_domain: str = Field(
        default="suporte-vps-whatsapp",
        alias="DEFAULT_DOMAIN",
    )
    domains_path: Path = Field(default=Path("domains"), alias="DOMAINS_PATH")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    recall_api_key: str | None = Field(default=None, alias="RECALL_API_KEY")
    zoom_webhook_secret: str | None = Field(
        default=None,
        alias="ZOOM_WEBHOOK_SECRET",
    )
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    retrieval_backend: str = Field(default="lexical", alias="RETRIEVAL_BACKEND")
    persistence_backend: str = Field(default="disabled", alias="PERSISTENCE_BACKEND")
    persistence_hash_secret: str | None = Field(
        default=None,
        alias="PERSISTENCE_HASH_SECRET",
    )
    enable_outbox_ingress: bool = Field(default=False, alias="ENABLE_OUTBOX_INGRESS")
    outbox_webhook_secret: str | None = Field(default=None, alias="OUTBOX_WEBHOOK_SECRET")
    n8n_verified_handoff_url: str | None = Field(
        default=None,
        alias="N8N_VERIFIED_HANDOFF_URL",
    )
    n8n_verified_whatsapp_url: str | None = Field(
        default=None,
        alias="N8N_VERIFIED_WHATSAPP_URL",
    )
    n8n_verified_otp_url: str | None = Field(
        default=None,
        alias="N8N_VERIFIED_OTP_URL",
    )
    conversation_retention_days: int = Field(
        default=60,
        alias="CONVERSATION_RETENTION_DAYS",
        ge=1,
    )
    database_connect_timeout_seconds: int = Field(
        default=5,
        alias="DATABASE_CONNECT_TIMEOUT_SECONDS",
        ge=1,
    )
    database_query_timeout_seconds: int = Field(
        default=10,
        alias="DATABASE_QUERY_TIMEOUT_SECONDS",
        ge=1,
    )
    database_pool_min_size: int = Field(default=1, alias="DATABASE_POOL_MIN_SIZE", ge=0)
    database_pool_max_size: int = Field(default=5, alias="DATABASE_POOL_MAX_SIZE", ge=1)
    api_secret_key: str | None = Field(default=None, alias="API_SECRET_KEY")
    rate_limit_per_minute: int = Field(default=30, alias="RATE_LIMIT_PER_MINUTE", ge=1)
    enable_chat_ui: bool = Field(default=False, alias="ENABLE_CHAT_UI")
    enable_public_chat_ui: bool = Field(
        default=False,
        alias="ENABLE_PUBLIC_CHAT_UI",
    )
    web_chat_rate_limit_per_minute: int = Field(
        default=10,
        alias="WEB_CHAT_RATE_LIMIT_PER_MINUTE",
        ge=0,
    )
    web_chat_session_cookie: str = Field(
        default="sfaq_web_session",
        alias="WEB_CHAT_SESSION_COOKIE",
    )
    web_chat_cookie_secure: bool | None = Field(
        default=None,
        alias="WEB_CHAT_COOKIE_SECURE",
    )
    project_llm_api_key_alias: str | None = Field(
        default=None,
        alias="PROJECT_LLM_API_KEY_ALIAS",
    )
    enable_web_whatsapp_auth: bool = Field(
        default=False,
        alias="ENABLE_WEB_WHATSAPP_AUTH",
    )
    web_auth_storage_backend: str = Field(
        default="memory",
        alias="WEB_AUTH_STORAGE_BACKEND",
    )
    otp_code_ttl_seconds: int = Field(default=300, alias="OTP_CODE_TTL_SECONDS", ge=1)
    otp_resend_cooldown_seconds: int = Field(
        default=60,
        alias="OTP_RESEND_COOLDOWN_SECONDS",
        ge=1,
    )
    otp_max_attempts: int = Field(default=5, alias="OTP_MAX_ATTEMPTS", ge=1)
    otp_start_limit_per_ip_per_hour: int = Field(
        default=10,
        alias="OTP_START_LIMIT_PER_IP_PER_HOUR",
        ge=1,
    )
    otp_start_limit_per_phone_per_15_minutes: int = Field(
        default=3,
        alias="OTP_START_LIMIT_PER_PHONE_PER_15_MINUTES",
        ge=1,
    )
    identity_hash_secret: str | None = Field(default=None, alias="IDENTITY_HASH_SECRET")
    otp_digest_secret: str | None = Field(default=None, alias="OTP_DIGEST_SECRET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_api_secret_outside_dev(self) -> Self:
        app_env = self.app_env.lower()
        self.web_chat_session_cookie = self.web_chat_session_cookie.strip() or "sfaq_web_session"
        if self.web_chat_cookie_secure is None:
            self.web_chat_cookie_secure = app_env not in DEV_ENVS

        if self.enable_public_chat_ui and app_env not in DEV_ENVS:
            if not self.web_chat_cookie_secure:
                raise ValueError(
                    "WEB_CHAT_COOKIE_SECURE must be true when ENABLE_PUBLIC_CHAT_UI is enabled outside development environments",
                )
            if self.web_chat_rate_limit_per_minute < 1:
                raise ValueError(
                    "WEB_CHAT_RATE_LIMIT_PER_MINUTE must be at least 1 when ENABLE_PUBLIC_CHAT_UI is enabled",
                )

        self.web_auth_storage_backend = self.web_auth_storage_backend.strip().lower()
        if self.web_auth_storage_backend not in {"memory", "postgres"}:
            raise ValueError("WEB_AUTH_STORAGE_BACKEND must be memory or postgres")
        if self.web_auth_storage_backend == "postgres":
            self.database_url = _normalize_required_secret(self.database_url, "DATABASE_URL")

        if self.enable_web_whatsapp_auth:
            self.identity_hash_secret = _normalize_required_secret(
                self.identity_hash_secret,
                "IDENTITY_HASH_SECRET",
            )
            self.otp_digest_secret = _normalize_required_secret(
                self.otp_digest_secret,
                "OTP_DIGEST_SECRET",
            )
            if self.identity_hash_secret == self.otp_digest_secret:
                raise ValueError(
                    "IDENTITY_HASH_SECRET and OTP_DIGEST_SECRET must be different",
                )

        persistence_backend = self.persistence_backend.strip().lower()
        if persistence_backend not in {"disabled", "postgres"}:
            raise ValueError("PERSISTENCE_BACKEND must be disabled or postgres")
        self.persistence_backend = persistence_backend
        if persistence_backend == "postgres":
            self.database_url = _normalize_required_secret(self.database_url, "DATABASE_URL")
            self.persistence_hash_secret = _normalize_required_secret(
                self.persistence_hash_secret,
                "PERSISTENCE_HASH_SECRET",
            )
        if self.enable_outbox_ingress:
            self.database_url = _normalize_required_secret(self.database_url, "DATABASE_URL")
            self.outbox_webhook_secret = _normalize_required_secret(
                self.outbox_webhook_secret,
                "OUTBOX_WEBHOOK_SECRET",
            )
        if self.database_pool_min_size > self.database_pool_max_size:
            raise ValueError("DATABASE_POOL_MIN_SIZE cannot exceed DATABASE_POOL_MAX_SIZE")

        if self.api_secret_key and self.api_secret_key.strip():
            self.api_secret_key = self.api_secret_key.strip()
            return self

        if app_env in DEV_ENVS:
            self.api_secret_key = LOCAL_DEV_API_KEY
            return self

        raise ValueError("API_SECRET_KEY is required outside development environments")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _normalize_required_secret(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise ValueError(f"{name} is required for the enabled PostgreSQL-backed feature")
