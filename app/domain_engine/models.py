from pathlib import Path

from pydantic import BaseModel, Field


class DomainRoutingConfig(BaseModel):
    keywords: list[str] = Field(default_factory=list)


class DomainResponseConfig(BaseModel):
    tone: str = "simples"
    max_context_chunks: int = 5
    max_answer_length: str = "short"


class DomainHandoffConfig(BaseModel):
    confidence_threshold: float = 0.7
    escalate_on: list[str] = Field(default_factory=list)


class DomainKnowledgeConfig(BaseModel):
    sources: list[str] = Field(default_factory=list)


class DomainLLMConfig(BaseModel):
    provider: str = "mock"
    model: str = "mock-model"
    embedding_model: str = "mock-embedding"


class DomainConfig(BaseModel):
    name: str
    display_name: str
    default_language: str = "pt-BR"
    root_path: Path
    routing: DomainRoutingConfig = Field(default_factory=DomainRoutingConfig)
    response: DomainResponseConfig = Field(default_factory=DomainResponseConfig)
    handoff: DomainHandoffConfig = Field(default_factory=DomainHandoffConfig)
    knowledge: DomainKnowledgeConfig = Field(default_factory=DomainKnowledgeConfig)
    llm: DomainLLMConfig = Field(default_factory=DomainLLMConfig)
