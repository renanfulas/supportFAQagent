from app.domain_engine.models import DomainConfig
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.wrapper import LLMWrapper


class LLMService:
    def get_provider(self, domain: DomainConfig) -> BaseLLMProvider:
        provider = domain.llm.provider.lower().strip()

        if provider == "mock":
            return MockLLMProvider()

        if provider in {"openai", "anthropic"}:
            return LLMWrapper(provider=provider, model=domain.llm.model)

        raise ValueError(f"LLM provider {domain.llm.provider} is not supported")
