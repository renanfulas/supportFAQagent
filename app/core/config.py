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
    verified_handoff_webhook_url: str | None = Field(
        default=None,
        alias="VERIFIED_HANDOFF_WEBHOOK_URL",
    )
    verified_whatsapp_webhook_url: str | None = Field(
        default=None,
        alias="VERIFIED_WHATSAPP_WEBHOOK_URL",
    )
    verified_otp_webhook_url: str | None = Field(
        default=None,
        alias="VERIFIED_OTP_WEBHOOK_URL",
    )
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
    conversation_history_messages: int = Field(
        default=4,
        alias="CONVERSATION_HISTORY_MESSAGES",
        ge=0,
        le=20,
    )
    persistence_hash_version: str = Field(
        default="hmac-sha256-v1",
        alias="PERSISTENCE_HASH_VERSION",
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
    web_auth_otp_delivery_transport: str = Field(
        default="memory",
        alias="WEB_AUTH_OTP_DELIVERY_TRANSPORT",
    )
    enable_meta_whatsapp_webhook: bool = Field(
        default=False,
        alias="ENABLE_META_WHATSAPP_WEBHOOK",
    )
    enable_meta_whatsapp_chat: bool = Field(
        default=False,
        alias="ENABLE_META_WHATSAPP_CHAT",
    )
    meta_whatsapp_access_token: str | None = Field(
        default=None,
        alias="META_WHATSAPP_ACCESS_TOKEN",
    )
    meta_whatsapp_app_secret: str | None = Field(
        default=None,
        alias="META_WHATSAPP_APP_SECRET",
    )
    meta_whatsapp_webhook_verify_token: str | None = Field(
        default=None,
        alias="META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    )
    meta_whatsapp_waba_id: str | None = Field(default=None, alias="META_WHATSAPP_WABA_ID")
    meta_whatsapp_phone_number_id: str | None = Field(
        default=None,
        alias="META_WHATSAPP_PHONE_NUMBER_ID",
    )
    meta_whatsapp_graph_api_version: str = Field(
        default="v25.0",
        alias="META_WHATSAPP_GRAPH_API_VERSION",
    )
    meta_whatsapp_request_timeout_seconds: int = Field(
        default=5,
        alias="META_WHATSAPP_REQUEST_TIMEOUT_SECONDS",
        ge=1,
    )
    meta_whatsapp_otp_template_name: str | None = Field(
        default=None,
        alias="META_WHATSAPP_OTP_TEMPLATE_NAME",
    )
    meta_whatsapp_otp_template_language: str = Field(
        default="pt_BR",
        alias="META_WHATSAPP_OTP_TEMPLATE_LANGUAGE",
    )
    hermes_base_url: str | None = Field(default=None, alias="HERMES_BASE_URL")
    hermes_webhook_secret: str | None = Field(default=None, alias="HERMES_WEBHOOK_SECRET")
    hermes_request_timeout_seconds: int = Field(
        default=5,
        alias="HERMES_REQUEST_TIMEOUT_SECONDS",
        ge=1,
    )
    hermes_otp_delivery_path: str = Field(
        default="/otp-delivery",
        alias="HERMES_OTP_DELIVERY_PATH",
    )

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
        self.web_auth_otp_delivery_transport = (
            self.web_auth_otp_delivery_transport.strip().lower() or "memory"
        )
        if self.web_auth_otp_delivery_transport not in {"memory", "meta", "hermes"}:
            raise ValueError("WEB_AUTH_OTP_DELIVERY_TRANSPORT must be memory, meta or hermes")

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
            if self.web_auth_otp_delivery_transport == "meta":
                self.meta_whatsapp_access_token = _normalize_required_secret(
                    self.meta_whatsapp_access_token,
                    "META_WHATSAPP_ACCESS_TOKEN",
                )
                self.meta_whatsapp_phone_number_id = _normalize_required_secret(
                    self.meta_whatsapp_phone_number_id,
                    "META_WHATSAPP_PHONE_NUMBER_ID",
                )
                self.meta_whatsapp_otp_template_name = _normalize_required_secret(
                    self.meta_whatsapp_otp_template_name,
                    "META_WHATSAPP_OTP_TEMPLATE_NAME",
                )
            if self.web_auth_otp_delivery_transport == "hermes":
                self.hermes_base_url = _normalize_required_secret(
                    self.hermes_base_url,
                    "HERMES_BASE_URL",
                )
                self.hermes_webhook_secret = _normalize_required_secret(
                    self.hermes_webhook_secret,
                    "HERMES_WEBHOOK_SECRET",
                )

        self.meta_whatsapp_graph_api_version = (
            self.meta_whatsapp_graph_api_version.strip() or "v25.0"
        )
        self.meta_whatsapp_otp_template_language = (
            self.meta_whatsapp_otp_template_language.strip() or "pt_BR"
        )
        self.hermes_otp_delivery_path = self.hermes_otp_delivery_path.strip() or "/otp-delivery"
        if not self.hermes_otp_delivery_path.startswith("/"):
            raise ValueError("HERMES_OTP_DELIVERY_PATH must start with /")
        if self.enable_meta_whatsapp_webhook:
            self.meta_whatsapp_app_secret = _normalize_required_secret(
                self.meta_whatsapp_app_secret,
                "META_WHATSAPP_APP_SECRET",
            )
            self.meta_whatsapp_webhook_verify_token = _normalize_required_secret(
                self.meta_whatsapp_webhook_verify_token,
                "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
            )
        if self.enable_meta_whatsapp_chat:
            self.meta_whatsapp_access_token = _normalize_required_secret(
                self.meta_whatsapp_access_token,
                "META_WHATSAPP_ACCESS_TOKEN",
            )
            self.meta_whatsapp_phone_number_id = _normalize_required_secret(
                self.meta_whatsapp_phone_number_id,
                "META_WHATSAPP_PHONE_NUMBER_ID",
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
            self.persistence_hash_version = (
                self.persistence_hash_version.strip() or "hmac-sha256-v1"
            )
        self.retrieval_backend = self.retrieval_backend.strip().lower()
        if self.retrieval_backend not in {"lexical", "pgvector"}:
            raise ValueError("RETRIEVAL_BACKEND must be lexical or pgvector")
        if self.retrieval_backend == "pgvector":
            self.database_url = _normalize_required_secret(self.database_url, "DATABASE_URL")
        if self.enable_outbox_ingress:
            self.database_url = _normalize_required_secret(self.database_url, "DATABASE_URL")
            self.outbox_webhook_secret = _normalize_required_secret(
                self.outbox_webhook_secret,
                "OUTBOX_WEBHOOK_SECRET",
            )
        self.verified_handoff_webhook_url = _resolve_delivery_url_alias(
            generic_value=self.verified_handoff_webhook_url,
            legacy_value=self.n8n_verified_handoff_url,
            generic_name="VERIFIED_HANDOFF_WEBHOOK_URL",
            legacy_name="N8N_VERIFIED_HANDOFF_URL",
            app_env=app_env,
        )
        self.verified_whatsapp_webhook_url = _resolve_delivery_url_alias(
            generic_value=self.verified_whatsapp_webhook_url,
            legacy_value=self.n8n_verified_whatsapp_url,
            generic_name="VERIFIED_WHATSAPP_WEBHOOK_URL",
            legacy_name="N8N_VERIFIED_WHATSAPP_URL",
            app_env=app_env,
        )
        self.verified_otp_webhook_url = _resolve_delivery_url_alias(
            generic_value=self.verified_otp_webhook_url,
            legacy_value=self.n8n_verified_otp_url,
            generic_name="VERIFIED_OTP_WEBHOOK_URL",
            legacy_name="N8N_VERIFIED_OTP_URL",
            app_env=app_env,
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


def _normalize_optional_text(value: str | None) -> str | None:
    if value and value.strip():
        return value.strip()
    return None


def _resolve_delivery_url_alias(
    *,
    generic_value: str | None,
    legacy_value: str | None,
    generic_name: str,
    legacy_name: str,
    app_env: str,
) -> str | None:
    generic = _normalize_optional_text(generic_value)
    legacy = _normalize_optional_text(legacy_value)
    if generic and legacy and generic != legacy and app_env not in DEV_ENVS:
        raise ValueError(
            f"{generic_name} conflicts with legacy {legacy_name}; use only the generic delivery URL",
        )
    return generic or legacy
