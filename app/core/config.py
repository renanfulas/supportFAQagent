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
    session_domain_store_backend: str = Field(
        default="memory", alias="SESSION_DOMAIN_STORE_BACKEND"
    )
    session_state_backend: str = Field(
        default="memory", alias="SESSION_STATE_BACKEND"
    )
    session_state_ttl_seconds: int = Field(
        default=2700, alias="SESSION_STATE_TTL_SECONDS"
    )
    session_state_redis_url: str | None = Field(
        default=None, alias="SESSION_STATE_REDIS_URL"
    )
    persistence_hash_secret: str | None = Field(
        default=None,
        alias="PERSISTENCE_HASH_SECRET",
    )
    enable_outbox_ingress: bool = Field(default=False, alias="ENABLE_OUTBOX_INGRESS")
    outbox_webhook_secret: str | None = Field(default=None, alias="OUTBOX_WEBHOOK_SECRET")
    enable_conversation_archive: bool = Field(
        default=False,
        alias="ENABLE_CONVERSATION_ARCHIVE",
    )
    enable_support_inbox: bool = Field(
        default=False,
        alias="ENABLE_SUPPORT_INBOX",
    )
    enable_conversation_summary: bool = Field(
        default=False,
        alias="ENABLE_CONVERSATION_SUMMARY",
    )
    enable_summary_recall: bool = Field(
        default=False,
        alias="ENABLE_SUMMARY_RECALL",
    )
    enable_support_team_whatsapp_notify: bool = Field(
        default=False,
        alias="ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY",
    )
    support_team_whatsapp_recipients: str = Field(
        default="",
        alias="SUPPORT_TEAM_WHATSAPP_RECIPIENTS",
    )
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
    conversation_retention_days: int = Field(
        default=60,
        alias="CONVERSATION_RETENTION_DAYS",
        ge=1,
    )
    conversation_history_messages: int = Field(
        default=8,
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
    enable_handoff_consent_gate: bool = Field(
        default=False,
        alias="ENABLE_HANDOFF_CONSENT_GATE",
    )
    otp_abandonment_reminder_minutes: int = Field(
        default=15,
        alias="OTP_ABANDONMENT_REMINDER_MINUTES",
        ge=1,
    )
    web_auth_otp_delivery_transport: str = Field(
        default="memory",
        alias="WEB_AUTH_OTP_DELIVERY_TRANSPORT",
    )
    enable_support_console: bool = Field(
        default=False,
        alias="ENABLE_SUPPORT_CONSOLE",
    )
    support_console_timezone: str = Field(
        default="America/Sao_Paulo",
        alias="SUPPORT_CONSOLE_TIMEZONE",
    )
    support_staff_session_expiry_hour: int = Field(
        default=4,
        alias="SUPPORT_STAFF_SESSION_EXPIRY_HOUR",
        ge=0,
        le=23,
    )
    support_staff_hint_ttl_days: int = Field(
        default=90,
        alias="SUPPORT_STAFF_HINT_TTL_DAYS",
        ge=1,
    )
    support_sla_minutes_urgent: int = Field(
        default=60,
        alias="SUPPORT_SLA_MINUTES_URGENT",
        ge=1,
    )
    support_sla_minutes_high: int = Field(
        default=120,
        alias="SUPPORT_SLA_MINUTES_HIGH",
        ge=1,
    )
    support_sla_minutes_normal: int = Field(
        default=480,
        alias="SUPPORT_SLA_MINUTES_NORMAL",
        ge=1,
    )
    support_sla_minutes_low: int = Field(
        default=1440,
        alias="SUPPORT_SLA_MINUTES_LOW",
        ge=1,
    )
    support_console_active_cases_cap: int = Field(
        default=500,
        alias="SUPPORT_CONSOLE_ACTIVE_CASES_CAP",
        ge=1,
    )
    support_otp_start_per_phone_per_hour: int = Field(
        default=5,
        alias="SUPPORT_OTP_START_PER_PHONE_PER_HOUR",
        ge=1,
    )
    support_otp_start_per_ip_per_hour: int = Field(
        default=20,
        alias="SUPPORT_OTP_START_PER_IP_PER_HOUR",
        ge=1,
    )
    support_console_reads_per_session_per_minute: int = Field(
        default=120,
        alias="SUPPORT_CONSOLE_READS_PER_SESSION_PER_MINUTE",
        ge=1,
    )
    enable_meta_whatsapp_webhook: bool = Field(
        default=False,
        alias="ENABLE_META_WHATSAPP_WEBHOOK",
    )
    enable_meta_whatsapp_chat: bool = Field(
        default=False,
        alias="ENABLE_META_WHATSAPP_CHAT",
    )
    enable_whatsapp_domain_router: bool = Field(
        default=False,
        alias="ENABLE_WHATSAPP_DOMAIN_ROUTER",
    )
    # Web chat V3: reuses the same conversational domain router as WhatsApp
    # (app/orchestration/channel_routing.py), gated by its own flag so rollout
    # timing is independent per channel. Domain list is shared on purpose
    # (whatsapp_router_domain_list below): "which domains this deployment
    # serves conversationally" is not a WhatsApp-only concept.
    enable_web_domain_router: bool = Field(
        default=False,
        alias="ENABLE_WEB_DOMAIN_ROUTER",
    )
    whatsapp_router_domains: str = Field(
        default="suporte-vps-whatsapp,vendas,suporte-hospedagem,suporte-vps",
        alias="WHATSAPP_ROUTER_DOMAINS",
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
    enable_hermes_chat: bool = Field(
        default=False,
        alias="ENABLE_HERMES_CHAT",
    )
    hermes_bridge_url: str = Field(
        default="http://127.0.0.1:3000",
        alias="HERMES_BRIDGE_URL",
    )
    hermes_chat_forward_secret: str | None = Field(
        default=None,
        alias="HERMES_CHAT_FORWARD_SECRET",
    )
    whatsapp_chat_rate_limit_per_minute: int = Field(
        default=20,
        ge=1,
        alias="WHATSAPP_CHAT_RATE_LIMIT_PER_MINUTE",
    )

    # Ponte WhatsApp<->console (numero de suporte, Meta-nativo). Dark por
    # padrao; ver docs/quality-plans/whatsapp-support-bridge-tech-plan.md.
    enable_whatsapp_support_number: bool = Field(
        default=False,
        alias="ENABLE_WHATSAPP_SUPPORT_NUMBER",
    )
    meta_support_phone_number_id: str | None = Field(
        default=None,
        alias="META_SUPPORT_PHONE_NUMBER_ID",
    )
    # Numero DISCAVEL (E.164) do numero de suporte, para o deep link wa.me --
    # distinto de meta_support_phone_number_id, que e o identificador interno
    # da Cloud API usado nas chamadas HTTP, nao um numero que o cliente digita.
    meta_support_phone_number_e164: str | None = Field(
        default=None,
        alias="META_SUPPORT_PHONE_NUMBER_E164",
    )
    meta_support_waba_id: str | None = Field(
        default=None,
        alias="META_SUPPORT_WABA_ID",
    )
    # Chave dedicada para cifrar o wa_id em repouso (nunca reusar
    # identity_hash_secret, que e para HMAC/hash, nao cifra reversivel).
    support_wa_enc_key: str | None = Field(
        default=None,
        alias="SUPPORT_WA_ENC_KEY",
    )
    # Secret dedicado para assinar o token do deep link (case_id auto-
    # verificavel); separado da chave de cifra por higiene de chaves.
    support_wa_token_secret: str | None = Field(
        default=None,
        alias="SUPPORT_WA_TOKEN_SECRET",
    )
    support_wa_binding_max_days: int = Field(
        default=15,
        ge=1,
        alias="SUPPORT_WA_BINDING_MAX_DAYS",
    )
    support_wa_window_hours: int = Field(
        default=24,
        ge=1,
        alias="SUPPORT_WA_WINDOW_HOURS",
    )
    support_business_hours_start: str = Field(
        default="09:00",
        alias="SUPPORT_BUSINESS_HOURS_START",
    )
    support_business_hours_end: str = Field(
        default="18:00",
        alias="SUPPORT_BUSINESS_HOURS_END",
    )
    support_business_days: str = Field(
        default="mon,tue,wed,thu,fri",
        alias="SUPPORT_BUSINESS_DAYS",
    )
    support_wa_reply_rate_limit_per_case_per_minute: int = Field(
        default=20,
        ge=1,
        alias="SUPPORT_WA_REPLY_RATE_LIMIT_PER_CASE_PER_MINUTE",
    )

    # Fase 2 - nomes de template aprovados na WABA. Default = nome interno,
    # para funcionar out-of-the-box em dev/testes (fake delivery); em
    # producao a Meta pode exigir nomes diferentes dos internos, ajustados
    # aqui sem mudar codigo.
    support_wa_template_language: str = Field(
        default="pt_BR",
        alias="SUPPORT_WA_TEMPLATE_LANGUAGE",
    )
    support_wa_template_atendente_assumiu: str = Field(
        default="atendente_assumiu",
        alias="SUPPORT_WA_TEMPLATE_ATENDENTE_ASSUMIU",
    )
    support_wa_template_precisa_info: str = Field(
        default="precisa_info",
        alias="SUPPORT_WA_TEMPLATE_PRECISA_INFO",
    )
    support_wa_template_ticket_resolvido: str = Field(
        default="ticket_resolvido",
        alias="SUPPORT_WA_TEMPLATE_TICKET_RESOLVIDO",
    )
    support_wa_template_reengajar: str = Field(
        default="reengajar",
        alias="SUPPORT_WA_TEMPLATE_REENGAJAR",
    )

    # Fase 3 (opcional, opt-in) da ponte WhatsApp<->console: unificacao de
    # identidade so via OTP web -- WhatsApp nativo continua pseudonimo por
    # padrao para quem nunca passa pelo web. Dark por padrao.
    enable_native_identity_link: bool = Field(
        default=False,
        alias="ENABLE_NATIVE_IDENTITY_LINK",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def whatsapp_router_domain_list(self) -> list[str]:
        seen: dict[str, None] = {}
        for item in self.whatsapp_router_domains.split(","):
            name = item.strip()
            if name:
                seen.setdefault(name, None)
        return list(seen)

    @property
    def support_team_whatsapp_recipient_list(self) -> list[str]:
        seen: dict[str, None] = {}
        for item in self.support_team_whatsapp_recipients.split(","):
            recipient = item.strip()
            if recipient:
                seen.setdefault(recipient, None)
        return list(seen)

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
        if self.enable_handoff_consent_gate and not self.enable_web_whatsapp_auth:
            raise ValueError(
                "ENABLE_HANDOFF_CONSENT_GATE requires ENABLE_WEB_WHATSAPP_AUTH=true"
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

        if self.enable_support_console:
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
            self.support_console_timezone = self.support_console_timezone.strip()
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(self.support_console_timezone)
            except Exception as exc:
                raise ValueError(
                    "SUPPORT_CONSOLE_TIMEZONE must be a valid IANA timezone",
                ) from exc
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
        self.hermes_bridge_url = self.hermes_bridge_url.strip() or "http://127.0.0.1:3000"
        if self.enable_hermes_chat:
            self.hermes_base_url = _normalize_required_secret(
                self.hermes_base_url,
                "HERMES_BASE_URL",
            )
            self.hermes_webhook_secret = _normalize_required_secret(
                self.hermes_webhook_secret,
                "HERMES_WEBHOOK_SECRET",
            )
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
        self.session_domain_store_backend = self.session_domain_store_backend.strip().lower()
        if self.session_domain_store_backend not in {"memory", "postgres"}:
            raise ValueError("SESSION_DOMAIN_STORE_BACKEND must be memory or postgres")
        if self.session_domain_store_backend == "postgres" and persistence_backend != "postgres":
            raise ValueError(
                "SESSION_DOMAIN_STORE_BACKEND=postgres requires PERSISTENCE_BACKEND=postgres"
            )
        self.session_state_backend = self.session_state_backend.strip().lower()
        if self.session_state_backend not in {"memory", "redis"}:
            raise ValueError("SESSION_STATE_BACKEND must be memory or redis")
        if self.session_state_backend == "redis" and not (self.session_state_redis_url or "").strip():
            raise ValueError("SESSION_STATE_BACKEND=redis requires SESSION_STATE_REDIS_URL")
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
        self.verified_handoff_webhook_url = _normalize_optional_text(
            self.verified_handoff_webhook_url
        )
        self.verified_whatsapp_webhook_url = _normalize_optional_text(
            self.verified_whatsapp_webhook_url
        )
        self.verified_otp_webhook_url = _normalize_optional_text(
            self.verified_otp_webhook_url
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
