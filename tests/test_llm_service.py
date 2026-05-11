from pathlib import Path

import pytest

from app.domain_engine.models import DomainConfig, DomainLLMConfig
from app.llm.mock_provider import MockLLMProvider
from app.llm.service import LLMService


def make_domain(provider: str = "mock", model: str = "mock-model") -> DomainConfig:
    return DomainConfig(
        name="test-domain",
        display_name="Test Domain",
        root_path=Path("."),
        llm=DomainLLMConfig(provider=provider, model=model),
    )


def test_llm_service_returns_mock_provider_by_default() -> None:
    provider = LLMService().get_provider(make_domain())

    assert isinstance(provider, MockLLMProvider)


def test_llm_service_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="not supported"):
        LLMService().get_provider(make_domain(provider="unknown"))


def test_llm_service_routes_real_provider_from_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeWrapper:
        def __init__(self, provider: str, model: str) -> None:
            captured["provider"] = provider
            captured["model"] = model

        def generate_answer(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)

    provider = LLMService().get_provider(
        make_domain(provider="openai", model="gpt-4o-mini")
    )

    assert isinstance(provider, FakeWrapper)
    assert captured == {"provider": "openai", "model": "gpt-4o-mini"}
