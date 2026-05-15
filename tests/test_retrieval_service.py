from pathlib import Path

import pytest

from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.service import RetrievalService, build_vector_store


def make_domain() -> DomainConfig:
    return DomainConfig(
        name="test-domain",
        display_name="Test Domain",
        root_path=Path("."),
    )


class FakeVectorStore:
    def search(self, domain: DomainConfig, query: str, top_k: int) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                source="fake.md",
                title=domain.display_name,
                text=query,
                score=1.0,
            )
        ]


class FailingVectorStore:
    def search(self, domain: DomainConfig, query: str, top_k: int) -> list[RetrievedChunk]:
        raise RuntimeError("boom")


class RetrievalErrorVectorStore:
    def search(self, domain: DomainConfig, query: str, top_k: int) -> list[RetrievedChunk]:
        raise RetrievalError("already mapped")


def test_build_vector_store_keeps_lexical_path_without_resolving_embeddings() -> None:
    store = build_vector_store(make_domain())

    assert isinstance(store, LexicalVectorStore)


def test_retrieval_service_uses_vector_store_adapter() -> None:
    chunks = RetrievalService(vector_store=FakeVectorStore()).retrieve(
        domain=make_domain(),
        question="hello",
    )

    assert chunks[0].source == "fake.md"
    assert chunks[0].text == "hello"


def test_retrieval_service_wraps_adapter_errors() -> None:
    with pytest.raises(RetrievalError):
        RetrievalService(vector_store=FailingVectorStore()).retrieve(
            domain=make_domain(),
            question="hello",
        )


def test_retrieval_service_preserves_mapped_retrieval_errors() -> None:
    with pytest.raises(RetrievalError, match="already mapped"):
        RetrievalService(vector_store=RetrievalErrorVectorStore()).retrieve(
            domain=make_domain(),
            question="hello",
        )
