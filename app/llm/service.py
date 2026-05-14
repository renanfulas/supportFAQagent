from app.domain_engine.models import DomainConfig
from app.core.errors import ProviderError
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.wrapper import LLMWrapper


class LLMService:
    def get_provider(
        self,
        domain: DomainConfig,
        api_key: str | None = None,
    ) -> BaseLLMProvider:
        provider = domain.llm.provider.lower().strip()

        if provider == "mock":
            return MockLLMProvider()

        if provider in {"openai", "anthropic"}:
            try:
                return LLMWrapper(
                    provider=provider,
                    model=domain.llm.model,
                    api_key=api_key,
                )
            except Exception as exc:
                raise ProviderError("provider initialization failed") from exc

        raise ValueError(f"LLM provider {domain.llm.provider} is not supported")
