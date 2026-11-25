"""Re-ingesting a domain into real PostgreSQL/pgvector is a sync, never a duplicate.

Skipped unless PHASE0_TEST_DATABASE_URL points to a disposable database
(``scripts/run_integration_tests.sh``).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.domain_engine.models import DomainConfig, DomainKnowledgeConfig
from app.ingestion.pgvector_writer import PgVectorIngestionWriter
from app.ingestion.service import IngestionService


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
CHUNK_SIZE = 200  # o splitter usa overlap 150: o chunk precisa ser maior


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    if not DATABASE_URL:
        return
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "apply"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "migrations failed in disposable test database"


class CountingEmbeddings:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        vectors = []
        for text in texts:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([(seed[i % len(seed)] + 1) / 256 for i in range(1536)])
        return vectors


@pytest.fixture
def pack(tmp_path: Path):
    name = f"ingest-test-{uuid.uuid4().hex[:8]}"
    root = tmp_path / name
    (root / "knowledge" / "articles").mkdir(parents=True)
    domain = DomainConfig(
        name=name,
        display_name="Ingest test",
        root_path=root,
        knowledge=DomainKnowledgeConfig(sources=["knowledge/articles"]),
    )
    yield domain, root / "knowledge" / "articles"

    import psycopg

    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM articles WHERE domain_id = (SELECT id FROM domains WHERE name = %s)", (name,))
        cursor.execute("DELETE FROM domains WHERE name = %s", (name,))


def sync(domain: DomainConfig) -> tuple:
    service = IngestionService()
    documents = service.load_domain_documents(domain)
    chunks = service.chunk_documents(documents, chunk_size=CHUNK_SIZE)
    provider = CountingEmbeddings()
    result = PgVectorIngestionWriter(database_url=DATABASE_URL).persist(
        domain=domain,
        documents=documents,
        chunks=chunks,
        embedding_provider=provider,
    )
    return result, provider


def counts(domain: DomainConfig) -> dict[str, int]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT count(*) FROM articles a JOIN domains d ON d.id = a.domain_id
                WHERE d.name = %s AND a.status = 'active'),
              (SELECT count(*) FROM articles a JOIN domains d ON d.id = a.domain_id
                WHERE d.name = %s AND a.status = 'archived'),
              (SELECT count(*) FROM article_chunks c JOIN articles a ON a.id = c.article_id
                JOIN domains d ON d.id = a.domain_id WHERE d.name = %s),
              (SELECT count(*) FROM article_chunks c JOIN articles a ON a.id = c.article_id
                JOIN domains d ON d.id = a.domain_id WHERE d.name = %s AND a.status = 'active')
            """,
            (domain.name,) * 4,
        )
        active, archived, chunks, searchable = cursor.fetchone()
    return {"active": active, "archived": archived, "chunks": chunks, "searchable": searchable}


def paragraphs(count: int, label: str) -> str:
    return "\n\n".join(
        f"{label} paragrafo {index}: como configurar o servico passo a passo com seguranca."
        for index in range(count)
    )


def test_rerun_over_unchanged_knowledge_changes_nothing(pack) -> None:
    domain, articles = pack
    (articles / "reiniciar.md").write_text(paragraphs(4, "reiniciar"), encoding="utf-8")
    (articles / "backup.md").write_text(paragraphs(3, "backup"), encoding="utf-8")

    first, first_provider = sync(domain)
    before = counts(domain)
    second, second_provider = sync(domain)

    assert first.embedded_chunks == first.chunks > 2
    assert second.embedded_chunks == 0 and second.reused_chunks == first.chunks
    assert second_provider.texts == []  # nenhum embedding pago de novo
    assert counts(domain) == before == {
        "active": 2,
        "archived": 0,
        "chunks": first.chunks,
        "searchable": first.chunks,
    }


def test_a_shorter_article_loses_its_trailing_chunks(pack) -> None:
    domain, articles = pack
    target = articles / "reiniciar.md"
    target.write_text(paragraphs(5, "reiniciar"), encoding="utf-8")
    first, _ = sync(domain)

    target.write_text(paragraphs(2, "reiniciar"), encoding="utf-8")
    second, provider = sync(domain)

    assert second.chunks < first.chunks
    assert second.removed_chunks == first.chunks - second.chunks
    assert counts(domain)["chunks"] == second.chunks
    # O inicio do artigo nao mudou: no maximo o ultimo chunk (com overlap) e novo.
    assert len(provider.texts) <= 1


def test_an_article_removed_from_the_pack_is_archived_and_can_come_back(pack) -> None:
    domain, articles = pack
    (articles / "reiniciar.md").write_text(paragraphs(2, "reiniciar"), encoding="utf-8")
    (articles / "antigo.md").write_text(paragraphs(2, "antigo"), encoding="utf-8")
    first, _ = sync(domain)
    old_text = (articles / "antigo.md").read_text(encoding="utf-8")

    (articles / "antigo.md").unlink()
    removed, _ = sync(domain)
    state = counts(domain)

    assert removed.archived_articles == 1
    assert state["active"] == 1 and state["archived"] == 1
    assert state["searchable"] < state["chunks"]  # a busca so ve artigos ativos

    (articles / "antigo.md").write_text(old_text, encoding="utf-8")
    back, provider = sync(domain)

    assert counts(domain)["archived"] == 0
    assert back.embedded_chunks == 0 and provider.texts == []  # reaproveita o embedding


def test_an_empty_pack_never_archives_the_base(pack) -> None:
    domain, articles = pack
    (articles / "reiniciar.md").write_text(paragraphs(2, "reiniciar"), encoding="utf-8")
    sync(domain)
    before = counts(domain)

    (articles / "reiniciar.md").unlink()
    result, _ = sync(domain)

    assert result.chunks == 0 and result.archived_articles == 0
    assert counts(domain) == before
