from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from app.core.errors import ProviderError
from app.domain_engine.models import DomainConfig, DomainLLMConfig
from app.llm.mock_provider import MockLLMProvider
from app.llm.service import LLMService
from app.llm.wrapper import LLMWrapper


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
    captured: dict[str, str | None] = {}

    class FakeWrapper:
        def __init__(
            self,
            provider: str,
            model: str,
            api_key: str | None = None,
        ) -> None:
            captured["provider"] = provider
            captured["model"] = model
            captured["api_key"] = api_key

        def generate_answer(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)

    provider = LLMService().get_provider(
        make_domain(provider="openai", model="gpt-4o-mini")
    )

    assert isinstance(provider, FakeWrapper)
    assert captured == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": None,
    }


def test_llm_service_passes_per_request_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeWrapper:
        def __init__(
            self,
            provider: str,
            model: str,
            api_key: str | None = None,
        ) -> None:
            captured["provider"] = provider
            captured["model"] = model
            captured["api_key"] = api_key

        def generate_answer(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)

    provider = LLMService().get_provider(
        make_domain(provider="openai", model="gpt-4o-mini"),
        api_key="sk-user-test",
    )

    assert isinstance(provider, FakeWrapper)
    assert captured == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-user-test",
    }


def test_llm_service_preserves_provider_initialization_failure_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWrapper:
        def __init__(
            self,
            provider: str,
            model: str,
            api_key: str | None = None,
        ) -> None:
            raise ProviderError(
                "provider credentials are not configured",
                failure_kind="missing_credentials",
            )

    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)

    with pytest.raises(ProviderError) as exc_info:
        LLMService().get_provider(make_domain(provider="openai", model="gpt-4o-mini"))

    assert exc_info.value.error_code == "provider_error"
    assert exc_info.value.failure_kind == "missing_credentials"


def test_llm_wrapper_classifies_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.llm.wrapper.get_settings",
        lambda: SimpleNamespace(openai_api_key=None, anthropic_api_key=None),
    )

    with pytest.raises(ProviderError) as exc_info:
        LLMWrapper(provider="openai", model="gpt-4o-mini")

    assert exc_info.value.error_code == "provider_error"
    assert exc_info.value.failure_kind == "missing_credentials"


def test_llm_wrapper_classifies_timeout_without_leaking_provider_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch, TimeoutClient)
    monkeypatch.setattr(
        "app.llm.wrapper.get_settings",
        lambda: SimpleNamespace(openai_api_key="sk-test", anthropic_api_key=None),
    )

    provider = LLMWrapper(provider="openai", model="gpt-4o-mini")

    with pytest.raises(ProviderError) as exc_info:
        provider.generate_answer("prompt")

    assert str(exc_info.value) == "provider request failed"
    assert exc_info.value.error_code == "provider_error"
    assert exc_info.value.failure_kind == "provider_timeout"


def test_llm_wrapper_classifies_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch, EmptyResponseClient)
    monkeypatch.setattr(
        "app.llm.wrapper.get_settings",
        lambda: SimpleNamespace(openai_api_key="sk-test", anthropic_api_key=None),
    )

    provider = LLMWrapper(provider="openai", model="gpt-4o-mini")

    with pytest.raises(ProviderError) as exc_info:
        provider.generate_answer("prompt")

    assert exc_info.value.error_code == "provider_error"
    assert exc_info.value.failure_kind == "empty_response"


class TimeoutClient:
    def __init__(self, **kwargs: object) -> None:
        pass

    def invoke(self, prompt: str) -> object:
        raise TimeoutError("sdk timed out with internal details")


class EmptyResponseClient:
    def __init__(self, **kwargs: object) -> None:
        pass

    def invoke(self, prompt: str) -> object:
        return SimpleNamespace(content="   ")


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    client_class: type,
) -> None:
    fake_module = ModuleType("langchain_openai")
    fake_module.ChatOpenAI = client_class
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
