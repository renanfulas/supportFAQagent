"""Unit tests of the pgvector writer with a scripted cursor.

The real SQL semantics (rerun without duplicates, stale chunks, archiving) are
proven against PostgreSQL in tests/integration/test_pgvector_ingestion_postgres.py.
"""

import hashlib
from pathlib import Path

import pytest

from app.domain_engine.models import DomainConfig, DomainEmbeddingConfig
from app.ingestion.models import KnowledgeChunk, KnowledgeDocument
from app.ingestion.pgvector_writer import PgVectorIngestionError, PgVectorIngestionWriter


MODEL = "text-embedding-3-small"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeEmbeddings:
    def __init__(self, values: list[list[float]], on_call=None) -> None:
        self.values = values
        self.requests: list[list[str]] = []
        self.on_call = on_call

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.on_call:
            self.on_call()
        self.requests.append(texts)
        return self.values[: len(texts)]


class FakeCursor:
    def __init__(self, stored: list[tuple] | None = None, rowcount: int = 0) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.stored = stored or []
        self.rowcount = rowcount
        self._ids = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.calls.append((" ".join(query.split()), params))

    def fetchone(self) -> tuple[str]:
        self._ids += 1
        return (f"id-{self._ids}",)

    def fetchall(self) -> list[tuple]:
        return list(self.stored)

    def queries(self, fragment: str) -> list[tuple[str, tuple[object, ...]]]:
        return [call for call in self.calls if fragment in call[0]]


class FakeConnection:
    def __init__(self, cursor: FakeCursor | None = None) -> None:
        self.cursor_instance = cursor or FakeCursor()
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    @property
    def committed(self) -> bool:
        return self.commits > 0


def make_domain(model: str = MODEL) -> DomainConfig:
    return DomainConfig(
        name="suporte-vps-whatsapp",
        display_name="Suporte VPS e WhatsApp",
        root_path=Path("domains/suporte-vps-whatsapp"),
        embedding=DomainEmbeddingConfig(model=model, dimensions=3),
    )


def doc(source: str, *texts: str) -> tuple[KnowledgeDocument, list[KnowledgeChunk]]:
    title = source.rsplit("/", 1)[-1]
    document = KnowledgeDocument(source=source, title=title, content="\n\n".join(texts))
    chunks = [
        KnowledgeChunk(source=source, title=title, text=text, chunk_index=index)
        for index, text in enumerate(texts)
    ]
    return document, chunks


def make_writer(connection: FakeConnection) -> PgVectorIngestionWriter:
    return PgVectorIngestionWriter(
        database_url="postgresql://private",
        connection_factory=lambda _: connection,
    )


def test_pgvector_writer_persists_documents_chunks_and_embeddings() -> None:
    connection = FakeConnection()
    document, chunks = doc("knowledge/articles/evolution.md", "Configure a Evolution API.")
    provider = FakeEmbeddings([[0.1, 0.2, 0.3]])

    result = make_writer(connection).persist(
        domain=make_domain(),
        documents=[document],
        chunks=chunks,
        embedding_provider=provider,
    )

    assert result.domain == "suporte-vps-whatsapp"
    assert (result.documents, result.chunks, result.embedded_chunks, result.reused_chunks) == (1, 1, 1, 0)
    assert connection.committed is True
    cursor = connection.cursor_instance
    [(chunk_query, chunk_params)] = cursor.queries("INSERT INTO article_chunks")
    assert chunk_params[-1] == "[0.1,0.2,0.3]"
    assert '"source": "knowledge/articles/evolution.md"' in str(chunk_params[-2])
    assert f'"embedding_model": "{MODEL}"' in str(chunk_params[-2])
    assert provider.requests == [["Configure a Evolution API."]]


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
    document, chunks = doc("a.md", "texto")

    with pytest.raises(PgVectorIngestionError, match="dimensions"):
        make_writer(FakeConnection()).persist(
            domain=make_domain(),
            documents=[document],
            chunks=chunks,
            embedding_provider=FakeEmbeddings([[0.1, 0.2]]),
        )


def test_unchanged_chunks_keep_their_embedding_and_call_no_provider() -> None:
    document, chunks = doc("a.md", "primeiro", "segundo")
    cursor = FakeCursor(stored=[("a.md", 0, sha("primeiro"), MODEL), ("a.md", 1, sha("segundo"), MODEL)])
    connection = FakeConnection(cursor)
    provider = FakeEmbeddings([])

    result = make_writer(connection).persist(
        domain=make_domain(), documents=[document], chunks=chunks, embedding_provider=provider
    )

    assert provider.requests == []
    assert (result.embedded_chunks, result.reused_chunks) == (0, 2)
    assert cursor.queries("INSERT INTO article_chunks") == []
    # O artigo continua ativo (upsert) mesmo sem chunk novo.
    assert len(cursor.queries("INSERT INTO articles")) == 1


def test_only_changed_chunks_are_embedded_again() -> None:
    document, chunks = doc("a.md", "primeiro", "segundo mudou")
    cursor = FakeCursor(stored=[("a.md", 0, sha("primeiro"), MODEL), ("a.md", 1, sha("segundo"), MODEL)])
    provider = FakeEmbeddings([[0.4, 0.5, 0.6]])

    result = make_writer(FakeConnection(cursor)).persist(
        domain=make_domain(), documents=[document], chunks=chunks, embedding_provider=provider
    )

    assert provider.requests == [["segundo mudou"]]
    assert (result.embedded_chunks, result.reused_chunks) == (1, 1)
    [(_, params)] = cursor.queries("INSERT INTO article_chunks")
    assert params[2] == 1 and params[-1] == "[0.4,0.5,0.6]"


def test_a_new_embedding_model_embeds_everything_again() -> None:
    document, chunks = doc("a.md", "primeiro")
    cursor = FakeCursor(stored=[("a.md", 0, sha("primeiro"), "modelo-antigo")])
    provider = FakeEmbeddings([[0.1, 0.1, 0.1]])

    result = make_writer(FakeConnection(cursor)).persist(
        domain=make_domain(), documents=[document], chunks=chunks, embedding_provider=provider
    )

    assert result.embedded_chunks == 1
    assert provider.requests == [["primeiro"]]


def test_trailing_chunks_are_deleted_and_missing_articles_archived() -> None:
    document, chunks = doc("a.md", "unico")
    cursor = FakeCursor(rowcount=2)

    result = make_writer(FakeConnection(cursor)).persist(
        domain=make_domain(),
        documents=[document],
        chunks=chunks,
        embedding_provider=FakeEmbeddings([[0.1, 0.2, 0.3]]),
    )

    [(delete_query, delete_params)] = cursor.queries("DELETE FROM article_chunks")
    assert "chunk_index >= %s" in delete_query and delete_params[1] == 1
    [(archive_query, archive_params)] = cursor.queries("UPDATE articles")
    assert "status = 'archived'" in archive_query
    assert "source_type = %s" in archive_query  # so artigos de markdown
    assert archive_params[1] == "markdown" and archive_params[2] == ["a.md"]
    assert (result.removed_chunks, result.archived_articles) == (2, 2)
    # Nunca apaga artigo: so arquiva.
    assert cursor.queries("DELETE FROM articles") == []


def test_an_empty_pack_never_archives_the_base() -> None:
    cursor = FakeCursor()
    provider = FakeEmbeddings([])

    result = make_writer(FakeConnection(cursor)).persist(
        domain=make_domain(), documents=[], chunks=[], embedding_provider=provider
    )

    assert cursor.queries("UPDATE articles") == []
    assert provider.requests == []
    assert (result.chunks, result.archived_articles) == (0, 0)


def test_no_transaction_is_open_while_the_provider_is_called() -> None:
    connection = FakeConnection()
    commits_at_call: list[int] = []
    document, chunks = doc("a.md", "texto")

    make_writer(connection).persist(
        domain=make_domain(),
        documents=[document],
        chunks=chunks,
        embedding_provider=FakeEmbeddings([[0.1, 0.2, 0.3]], on_call=lambda: commits_at_call.append(connection.commits)),
    )

    assert commits_at_call == [1]  # a leitura ja foi commitada
    assert connection.commits == 2


def test_provider_errors_never_leak_their_message() -> None:
    class Boom:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("Incorrect API key provided: sk-proj-abc123")

    document, chunks = doc("a.md", "texto")

    with pytest.raises(PgVectorIngestionError) as raised:
        make_writer(FakeConnection()).persist(
            domain=make_domain(), documents=[document], chunks=chunks, embedding_provider=Boom()
        )

    assert "RuntimeError" in str(raised.value)
    assert "sk-proj" not in str(raised.value)


def test_database_errors_become_a_generic_message() -> None:
    class BrokenConnection(FakeConnection):
        def cursor(self) -> FakeCursor:
            raise ConnectionError("password authentication failed for user supportfaq")

    with pytest.raises(PgVectorIngestionError, match="^pgvector ingestion failed$"):
        make_writer(BrokenConnection()).persist(
            domain=make_domain(), documents=[], chunks=[], embedding_provider=FakeEmbeddings([])
        )
