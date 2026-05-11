from pathlib import Path

from app.core.errors import ProviderError, RetrievalError
from app.domain_engine.models import DomainConfig
from app.orchestration.chat_flow import ChatFlowService
from app.retrieval.models import RetrievedChunk


def make_domain() -> DomainConfig:
    return DomainConfig(
        name="test-domain",
        display_name="Test Domain",
        root_path=Path("."),
    )


class FailingRetrievalService:
    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        raise RetrievalError("failed")


class WorkingRetrievalService:
    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                source="source.md",
                title="Source",
                text="Context",
                score=1.0,
            )
        ]


class FailingLLMService:
    def get_provider(self, domain: DomainConfig):
        raise ProviderError("failed")


def test_chat_flow_returns_observable_retrieval_error() -> None:
    service = ChatFlowService()
    service.retrieval_service = FailingRetrievalService()

    response = service.answer(
        domain=make_domain(),
        question="hello",
        request_id="req-1",
    )

    assert response["request_id"] == "req-1"
    assert response["error_code"] == "retrieval_error"
    assert response["escalated"] is True
    assert "retrieval_error" in response["handoff_reasons"]


def test_chat_flow_returns_observable_provider_error() -> None:
    service = ChatFlowService()
    service.retrieval_service = WorkingRetrievalService()
    service.llm_service = FailingLLMService()

    response = service.answer(
        domain=make_domain(),
        question="hello",
        request_id="req-2",
    )

    assert response["request_id"] == "req-2"
    assert response["error_code"] == "provider_error"
    assert response["escalated"] is True
    assert "provider_error" in response["handoff_reasons"]
