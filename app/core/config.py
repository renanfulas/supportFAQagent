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
    raise ValueError(f"{name} is required when ENABLE_WEB_WHATSAPP_AUTH is enabled")
