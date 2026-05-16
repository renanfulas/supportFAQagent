from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig, DomainEmbeddingConfig
from app.retrieval.pgvector_store import PgVectorStore, PostgresPgVectorSearchBackend


def make_domain(*, embedding_dimensions: int = 1536) -> DomainConfig:
    return DomainConfig(
        name="test-domain",
        display_name="Test Domain",
        root_path=Path("."),
        embedding=DomainEmbeddingConfig(dimensions=embedding_dimensions),
    )


class FakeEmbeddingFunction:
    def __init__(self, embedding: list[float] | None = None) -> None:
        self.embedding = embedding or [0.1, 0.2, 0.3]
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.embedding


class FakeSearchBackend:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or [
            {
                "id": "chunk-1",
                "source": "knowledge/faqs/test.md",
                "title": "FAQ Teste",
                "chunk_text": "texto recuperado",
                "similarity": 0.91,
            }
        ]
        self.calls: list[dict[str, Any]] = []

    def search_chunks(
        self,
        *,
        domain: DomainConfig,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "domain": domain,
                "query_embedding": query_embedding,
                "top_k": top_k,
            }
        )
        return self.rows[:top_k]


class FailingEmbeddingFunction:
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


class FailingSearchBackend:
    def search_chunks(
        self,
        *,
        domain: DomainConfig,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        raise RuntimeError("database unavailable")


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: tuple[Any, ...] = ()

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.fake_cursor


class FakeConnectionFactory:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.cursor = FakeCursor(
            rows
            or [
                (
                    "knowledge/faqs/test.md",
                    "FAQ Teste",
                    "texto recuperado",
                    0.91,
                )
            ]
        )
        self.database_urls: list[str] = []

    def __call__(self, database_url: str) -> FakeConnection:
        self.database_urls.append(database_url)
        return FakeConnection(self.cursor)


def test_pgvector_store_maps_backend_rows_to_retrieved_chunks() -> None:
    embedding = FakeEmbeddingFunction()
    backend = FakeSearchBackend()
    store = PgVectorStore(
        embedding_function=embedding,
        search_backend=backend,
    )

    chunks = store.search(
        domain=make_domain(),
        query="como conectar whatsapp",
        top_k=5,
    )

    assert embedding.queries == ["como conectar whatsapp"]
    assert backend.calls[0]["domain"].name == "test-domain"
    assert backend.calls[0]["query_embedding"] == [0.1, 0.2, 0.3]
    assert backend.calls[0]["top_k"] == 5
    assert chunks[0].source == "knowledge/faqs/test.md"
    assert chunks[0].title == "FAQ Teste"
    assert chunks[0].text == "texto recuperado"
    assert chunks[0].score == 0.91


def test_pgvector_store_accepts_callable_embedding_function() -> None:
    backend = FakeSearchBackend()
    store = PgVectorStore(
        embedding_function=lambda query: [0.4, 0.5, 0.6],
        search_backend=backend,
    )

    store.search(domain=make_domain(), query="qrcode", top_k=1)

    assert backend.calls[0]["query_embedding"] == [0.4, 0.5, 0.6]


def test_pgvector_store_respects_top_k_from_backend_contract() -> None:
    backend = FakeSearchBackend(
        rows=[
            {"id": "1", "chunk_text": "um", "similarity": 0.9},
            {"id": "2", "chunk_text": "dois", "similarity": 0.8},
        ]
    )
    store = PgVectorStore(
        embedding_function=FakeEmbeddingFunction(),
        search_backend=backend,
    )

    chunks = store.search(domain=make_domain(), query="teste", top_k=1)

    assert len(chunks) == 1
    assert chunks[0].source == "1"


def test_pgvector_store_maps_embedding_failure_to_retrieval_error() -> None:
    store = PgVectorStore(
        embedding_function=FailingEmbeddingFunction(),
        search_backend=FakeSearchBackend(),
    )

    with pytest.raises(RetrievalError):
        store.search(domain=make_domain(), query="teste", top_k=1)


def test_pgvector_store_maps_backend_failure_to_retrieval_error() -> None:
    store = PgVectorStore(
        embedding_function=FakeEmbeddingFunction(),
        search_backend=FailingSearchBackend(),
    )

    with pytest.raises(RetrievalError):
        store.search(domain=make_domain(), query="teste", top_k=1)


def test_pgvector_store_rejects_rows_without_traceable_source() -> None:
    store = PgVectorStore(
        embedding_function=FakeEmbeddingFunction(),
        search_backend=FakeSearchBackend(
            rows=[{"chunk_text": "sem fonte rastreavel", "similarity": 0.8}]
        ),
    )

    with pytest.raises(RetrievalError):
        store.search(domain=make_domain(), query="teste", top_k=1)


def test_pgvector_store_normalizes_score_bounds() -> None:
    store = PgVectorStore(
        embedding_function=FakeEmbeddingFunction(),
        search_backend=FakeSearchBackend(
            rows=[
                {"id": "alto", "chunk_text": "score alto", "similarity": 1.5},
                {"id": "baixo", "chunk_text": "score baixo", "similarity": -0.5},
            ]
        ),
    )

    chunks = store.search(domain=make_domain(), query="teste", top_k=2)

    assert chunks[0].score == 1.0
    assert chunks[1].score == 0.0


def test_postgres_pgvector_backend_uses_database_url_and_domain_filter() -> None:
    factory = FakeConnectionFactory()
    backend = PostgresPgVectorSearchBackend(
        database_url="postgresql://example",
        connection_factory=factory,
    )

    rows = backend.search_chunks(
        domain=make_domain(embedding_dimensions=3),
        query_embedding=[0.1, 0.2, 0.3],
        top_k=5,
    )

    assert factory.database_urls == ["postgresql://example"]
    assert rows[0]["source"] == "knowledge/faqs/test.md"
    assert rows[0]["score"] == 0.91
    assert "WHERE name = %s" in factory.cursor.sql
    assert "domains.status" not in factory.cursor.sql
    assert "c.domain_id = (SELECT id FROM resolved_domain)" in factory.cursor.sql
    assert "a.status = 'active'" in factory.cursor.sql
    assert factory.cursor.params == (
        "test-domain",
        "[0.1,0.2,0.3]",
        "[0.1,0.2,0.3]",
        5,
    )


def test_postgres_pgvector_backend_bounds_top_k_to_domain_limit() -> None:
    factory = FakeConnectionFactory()
    backend = PostgresPgVectorSearchBackend(
        database_url="postgresql://example",
        connection_factory=factory,
    )

    backend.search_chunks(
        domain=make_domain(embedding_dimensions=3),
        query_embedding=[0.1, 0.2, 0.3],
        top_k=999,
    )

    assert factory.cursor.params[-1] == 5


def test_postgres_pgvector_backend_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.pgvector_store.get_settings",
        lambda: SimpleNamespace(database_url=None),
    )
    backend = PostgresPgVectorSearchBackend(connection_factory=FakeConnectionFactory())

    with pytest.raises(RetrievalError, match="DATABASE_URL"):
        backend.search_chunks(
            domain=make_domain(embedding_dimensions=3),
            query_embedding=[0.1, 0.2, 0.3],
            top_k=1,
        )


def test_postgres_pgvector_backend_validates_embedding_dimensions() -> None:
    backend = PostgresPgVectorSearchBackend(
        database_url="postgresql://example",
        connection_factory=FakeConnectionFactory(),
    )

    with pytest.raises(RetrievalError, match="invalid dimensions"):
        backend.search_chunks(
            domain=make_domain(embedding_dimensions=1536),
            query_embedding=[0.1, 0.2, 0.3],
            top_k=1,
        )
