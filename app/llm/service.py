from app.domain_engine.models import DomainConfig
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockLLMProvider


class LLMService:
    def get_provider(self, domain: DomainConfig) -> BaseLLMProvider:
        # O MVP comeca com um provider mock para desacoplar a arquitetura.
        _ = domain
        return MockLLMProvider()
