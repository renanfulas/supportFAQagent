"""Installation-level configuration: who the deployment speaks for.

Domains (``domains/<x>/domain.yaml``) describe *what* the agent does in an area.
Some customer-facing text belongs to the whole installation instead: the
institutional greeting shown when a multi-domain channel cannot route a message
yet, the clarification question, and the copy of the local chat UI. That text
lives in an optional ``installation.yaml`` at the root of ``DOMAINS_PATH`` (the
client pack), never hardcoded in the core.

When the file is missing or invalid the installation falls back to neutral
defaults built from the routable domains, so a fresh install never shows another
company's brand.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


logger = logging.getLogger(__name__)

INSTALLATION_FILE_NAME = "installation.yaml"


class InstallationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstallationBrandConfig(InstallationModel):
    # Name used by the neutral greeting ("assistente virtual de <name>").
    name: str | None = None


class InstallationRoutingConfig(InstallationModel):
    # Full override of the router's unrouted-turn texts. None = neutral default
    # generated from the routable domains' display names.
    greeting: str | None = None
    clarification: str | None = None


class ChatUIQuickPrompt(InstallationModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=80)
    preview: str = Field(default="", max_length=160)
    message: str = Field(min_length=1, max_length=4000)


class InstallationChatUIConfig(InstallationModel):
    page_title: str = "Atendimento"
    kicker: str = "Atendimento assistido"
    heading: str = "Atendimento"
    subtitle: str = "respostas com base na documentação e escalonamento humano quando precisar"
    intro: str = (
        "Descreva sua dúvida com o máximo de contexto útil. Eu respondo com base na "
        "documentação disponível e, se o caso ficar sensível ou incompleto, sinalizo "
        "continuidade humana."
    )
    input_placeholder: str = "Descreva sua dúvida"
    composer_note: str = (
        "Quanto melhor o contexto, melhor a triagem. Se eu não tiver base suficiente, "
        "devolvo um código para continuidade no suporte."
    )
    quick_prompts: list[ChatUIQuickPrompt] = Field(default_factory=list, max_length=12)


class InstallationConfig(InstallationModel):
    contract_version: int = Field(default=1, ge=1)
    brand: InstallationBrandConfig = Field(default_factory=InstallationBrandConfig)
    routing: InstallationRoutingConfig = Field(default_factory=InstallationRoutingConfig)
    chat_ui: InstallationChatUIConfig = Field(default_factory=InstallationChatUIConfig)

    @field_validator("contract_version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported installation contract_version")
        return value


def load_installation_config(domains_path: Path) -> InstallationConfig:
    """Load ``<domains_path>/installation.yaml``, or neutral defaults.

    Never raises: a missing file is the normal case for a fresh install, and an
    invalid file is logged (without its content) and ignored, so a typo in the
    client pack cannot take a channel down.
    """
    path = Path(domains_path) / INSTALLATION_FILE_NAME
    if not path.exists():
        return InstallationConfig()

    try:
        with path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
        if not isinstance(raw, dict):
            raise ValueError("installation.yaml must be a mapping")
        return InstallationConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValueError, ValidationError) as error:
        logger.warning(
            "installation_config_invalid",
            extra={"error_type": type(error).__name__},
        )
        return InstallationConfig()
