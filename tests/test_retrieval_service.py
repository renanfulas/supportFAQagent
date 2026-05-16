from pathlib import Path

import pytest

from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.ingestion.models import KnowledgeChunk
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.pgvector_store import PgVectorStore
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


def test_build_vector_store_can_select_pgvector_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.service.get_settings",
        lambda: type("Settings", (), {"retrieval_backend": "pgvector"})(),
    )
    monkeypatch.setattr(
        "app.retrieval.service.get_domain_embeddings",
        lambda domain: lambda query: [0.1] * domain.embedding.dimensions,
    )

    store = build_vector_store(make_domain())

    assert isinstance(store, PgVectorStore)


def test_build_vector_store_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.service.get_settings",
        lambda: type("Settings", (), {"retrieval_backend": "unknown"})(),
    )

    with pytest.raises(RetrievalError, match="not supported"):
        build_vector_store(make_domain())


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


def test_retrieval_service_uses_factory_when_no_adapter_is_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_store = FakeVectorStore()
    calls: list[DomainConfig] = []

    def fake_build_vector_store(domain: DomainConfig) -> FakeVectorStore:
        calls.append(domain)
        return fake_store

    monkeypatch.setattr("app.retrieval.service.build_vector_store", fake_build_vector_store)

    chunks = RetrievalService().retrieve(
        domain=make_domain(),
        question="factory path",
    )

    assert len(calls) == 1
    assert calls[0].name == "test-domain"
    assert chunks[0].text == "factory path"


def test_lexical_store_orders_equal_scores_deterministically() -> None:
    store = LexicalVectorStore()
    store.ingestion_service.load_domain_documents = lambda domain: []  # type: ignore[method-assign]
    store.ingestion_service.chunk_documents = lambda documents: [  # type: ignore[method-assign]
        KnowledgeChunk(source="z.md", title="Z", text="alpha beta", chunk_index=0),
        KnowledgeChunk(source="a.md", title="A", text="alpha beta", chunk_index=0),
    ]

    chunks = store.search(
        domain=make_domain(),
        query="alpha",
        top_k=2,
    )

    assert [chunk.source for chunk in chunks] == ["a.md", "z.md"]
