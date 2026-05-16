from pathlib import Path

import pytest

from app.domain_engine.models import DomainConfig, DomainEmbeddingConfig
from app.ingestion.models import KnowledgeChunk, KnowledgeDocument
from app.ingestion.pgvector_writer import PgVectorIngestionError, PgVectorIngestionWriter


class FakeEmbeddings:
    def __init__(self, values: list[list[float]]) -> None:
        self.values = values
        self.requests: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.requests.append(texts)
        return self.values


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.rows = iter([("domain-id",), ("article-id",)])

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.calls.append((query, params))

    def fetchone(self) -> tuple[str]:
        return next(self.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.committed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


def make_domain() -> DomainConfig:
    return DomainConfig(
        name="suporte-vps-whatsapp",
        display_name="Suporte VPS e WhatsApp",
        root_path=Path("domains/suporte-vps-whatsapp"),
        embedding=DomainEmbeddingConfig(dimensions=3),
    )


def test_pgvector_writer_persists_documents_chunks_and_embeddings() -> None:
    connection = FakeConnection()
    writer = PgVectorIngestionWriter(
        database_url="postgresql://private",
        connection_factory=lambda _: connection,
    )
    documents = [
        KnowledgeDocument(
            source="knowledge/articles/evolution.md",
            title="Evolution",
            content="Configure a Evolution API.",
        )
    ]
    chunks = [
        KnowledgeChunk(
            source="knowledge/articles/evolution.md",
            title="Evolution",
            text="Configure a Evolution API.",
            chunk_index=0,
        )
    ]

    result = writer.persist(
        domain=make_domain(),
        documents=documents,
        chunks=chunks,
        embedding_provider=FakeEmbeddings([[0.1, 0.2, 0.3]]),
    )

    assert result.domain == "suporte-vps-whatsapp"
    assert result.documents == 1
    assert result.chunks == 1
    assert result.embedded_chunks == 1
    assert connection.committed is True
    assert len(connection.cursor_instance.calls) == 3
    chunk_query, chunk_params = connection.cursor_instance.calls[-1]
    assert "article_chunks" in chunk_query
    assert chunk_params[-1] == "[0.1,0.2,0.3]"
    assert '"source": "knowledge/articles/evolution.md"' in str(chunk_params[-2])


def test_pgvector_writer_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSettings:
        database_url = None

    monkeypatch.setattr(
        "app.ingestion.pgvector_writer.get_settings",
        lambda: FakeSettings(),
    )
    writer = PgVectorIngestionWriter(database_url=None)

    with pytest.raises(PgVectorIngestionError, match="DATABASE_URL"):
        writer.persist(
            domain=make_domain(),
            documents=[],
            chunks=[],
            embedding_provider=FakeEmbeddings([]),
        )


def test_pgvector_writer_validates_embedding_dimensions() -> None:
    writer = PgVectorIngestionWriter(
        database_url="postgresql://private",
        connection_factory=lambda _: FakeConnection(),
    )

    with pytest.raises(PgVectorIngestionError, match="dimensions"):
        writer.persist(
            domain=make_domain(),
            documents=[
                KnowledgeDocument(source="a.md", title="A", content="texto")
            ],
            chunks=[
                KnowledgeChunk(source="a.md", title="A", text="texto", chunk_index=0)
            ],
            embedding_provider=FakeEmbeddings([[0.1, 0.2]]),
        )
