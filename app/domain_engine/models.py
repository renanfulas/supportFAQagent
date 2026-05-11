from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DomainBehaviorConfig(DomainModel):
    persona: str = "agente de suporte"
    primary_goal: str = "responder com clareza usando a base de conhecimento"
    answer_guidelines: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class DomainRoutingConfig(DomainModel):
    keywords: list[str] = Field(default_factory=list)


class DomainResponseConfig(DomainModel):
    tone: str = "simples"
    max_context_chunks: int = Field(default=5, ge=1, le=20)
    max_answer_length: str = "short"
    no_context_message: str = (
        "Nao encontrei contexto suficiente na base atual. "
        "Vale revisar os artigos deste dominio ou escalar para humano."
    )
    provider_error_message: str = (
        "Nao consegui gerar uma resposta automatica agora. "
        "Escalando para atendimento humano."
    )


class DomainHandoffConfig(DomainModel):
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    escalate_on: list[str] = Field(default_factory=list)
    explicit_human_phrases: list[str] = Field(default_factory=list)
    sensitive_terms: list[str] = Field(default_factory=list)


class DomainKnowledgeConfig(DomainModel):
    sources: list[str] = Field(default_factory=list)


class DomainLLMConfig(DomainModel):
    provider: str = "mock"
    model: str = "mock-model"
    embedding_model: str = "mock-embedding"


class DomainEmbeddingConfig(DomainModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dimensions: int = 1536


class DomainConfig(DomainModel):
    contract_version: int = Field(default=1, ge=1)
    name: str
    display_name: str
    description: str = ""
    owner: str = "community"
    default_language: str = "pt-BR"
    root_path: Path
    behavior: DomainBehaviorConfig = Field(default_factory=DomainBehaviorConfig)
    routing: DomainRoutingConfig = Field(default_factory=DomainRoutingConfig)
    response: DomainResponseConfig = Field(default_factory=DomainResponseConfig)
    handoff: DomainHandoffConfig = Field(default_factory=DomainHandoffConfig)
    knowledge: DomainKnowledgeConfig = Field(default_factory=DomainKnowledgeConfig)
    llm: DomainLLMConfig = Field(default_factory=DomainLLMConfig)
    embedding: DomainEmbeddingConfig = Field(default_factory=DomainEmbeddingConfig)
