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
    api_secret_key: str | None = Field(default=None, alias="API_SECRET_KEY")
    rate_limit_per_minute: int = Field(default=30, alias="RATE_LIMIT_PER_MINUTE")
    enable_chat_ui: bool = Field(default=False, alias="ENABLE_CHAT_UI")
    project_llm_api_key_alias: str | None = Field(
        default=None,
        alias="PROJECT_LLM_API_KEY_ALIAS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_api_secret_outside_dev(self) -> Self:
        app_env = self.app_env.lower()
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
