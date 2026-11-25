"""Tests for scripts/ingest_domain_pgvector.py (the pack sync used by install.sh --pgvector)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.pgvector_writer import PgVectorIngestionError, PgVectorIngestionResult
from scripts import ingest_domain_pgvector as ingest
from scripts.ingest_domain_pgvector import (
    EXIT_CONFIG,
    EXIT_DEFAULT_EMPTY,
    EXIT_FAILED,
    EXIT_OK,
    DomainOutcome,
    LazyEmbeddings,
    exit_status,
    ingest_domain,
    render_markdown,
    render_plain,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_URL = "postgresql://supportfaq:very-private-password@postgres:5432/supportfaq"


def result(name: str, chunks: int = 2, embedded: int = 2) -> PgVectorIngestionResult:
    return PgVectorIngestionResult(
        domain=name,
        documents=1,
        chunks=chunks,
        embedded_chunks=embedded,
        reused_chunks=chunks - embedded,
        removed_chunks=0,
        archived_articles=0,
    )


class ReusingWriter:
    """Every chunk is already stored: the provider is never asked for embeddings."""

    def persist(self, *, domain, documents, chunks, embedding_provider):
        return result(domain.name, chunks=len(chunks), embedded=0)


class EmbeddingWriter:
    def persist(self, *, domain, documents, chunks, embedding_provider):
        embedding_provider.embed_documents([chunk.text for chunk in chunks])
        return result(domain.name, chunks=len(chunks))


def real_domain():
    from app.domain_engine.loader import DomainLoader

    return DomainLoader(REPO_ROOT / "domains").load("suporte-vps-whatsapp")


def test_unchanged_knowledge_never_creates_the_embedding_provider() -> None:
    created: list[str] = []

    outcome = ingest_domain(
        real_domain(),
        DB_URL,
        writer=ReusingWriter(),
        embeddings_factory=lambda domain: created.append(domain.name),
    )

    assert outcome.error is None and outcome.result.embedded_chunks == 0
    assert created == []  # rerun sem mudanca nao precisa nem de chave


def test_missing_embedding_key_is_a_configuration_error() -> None:
    def no_key(domain):
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")

    class Writer:
        def persist(self, *, domain, documents, chunks, embedding_provider):
            try:
                embedding_provider.embed_documents(["texto"])
            except Exception as exc:
                raise PgVectorIngestionError("embedding provider failed") from exc

    outcome = ingest_domain(real_domain(), DB_URL, writer=Writer(), embeddings_factory=no_key)

    assert outcome.config_error is True
    assert "OPENAI_API_KEY" in outcome.error and "openai" in outcome.error
    assert exit_status([outcome], default_domain="x") == EXIT_CONFIG


def test_lazy_embeddings_creates_the_provider_once() -> None:
    calls: list[int] = []

    class Provider:
        def embed_documents(self, texts):
            return [[1.0] for _ in texts]

    lazy = LazyEmbeddings(lambda: calls.append(1) or Provider())
    lazy.embed_documents(["a"])
    lazy.embed_documents(["b"])

    assert calls == [1]


def test_exit_status_rules() -> None:
    ok = DomainOutcome("a", result=result("a"))
    empty_default = DomainOutcome("padrao", result=result("padrao", chunks=0, embedded=0))
    failed = DomainOutcome("b", error="pgvector ingestion failed")

    assert exit_status([ok], default_domain="a") == EXIT_OK
    assert exit_status([ok, empty_default], default_domain="padrao") == EXIT_DEFAULT_EMPTY
    # Outro dominio vazio nao impede a troca: so o padrao e cobrado pelo readiness.
    assert exit_status([ok, empty_default], default_domain="a") == EXIT_OK
    assert exit_status([ok, failed], default_domain="a") == EXIT_FAILED


def test_reports_carry_counts_but_never_the_database_url() -> None:
    outcomes = [
        DomainOutcome("a", result=result("a", chunks=3, embedded=1)),
        DomainOutcome("b", error="embedding provider failed (AuthenticationError)"),
    ]

    markdown = render_markdown(outcomes, EXIT_FAILED, "a")
    plain = render_plain(outcomes)

    assert markdown.startswith("## Busca vetorial (pgvector)")
    assert "| `a` | 1 | 3 | 1 | 2 | 0 | 0 |" in markdown
    assert "AuthenticationError" in markdown
    assert "reused_chunks=2" in plain and "status=failed" in plain
    for text in (markdown, plain):
        assert "very-private-password" not in text and "postgres:5432" not in text


def _settings(**overrides):
    values = {
        "database_url": DB_URL,
        "domains_path": REPO_ROOT / "domains",
        "default_domain": "suporte-vps-whatsapp",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_main_requires_a_database_url(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings(database_url=None))

    assert ingest.main([]) == EXIT_CONFIG
    assert "DATABASE_URL" in capsys.readouterr().err


def test_main_rejects_an_unknown_domain(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())

    assert ingest.main(["--domain", "nao-existe"]) == EXIT_CONFIG
    assert "nao-existe" in capsys.readouterr().err


def test_main_all_syncs_every_domain_of_the_pack(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
    seen: list[str] = []

    def fake_ingest(domain, database_url, *, chunk_size=800):
        seen.append(domain.name)
        return DomainOutcome(domain.name, result=result(domain.name))

    monkeypatch.setattr(ingest, "ingest_domain", fake_ingest)

    assert ingest.main(["--all", "--markdown"]) == EXIT_OK
    out = capsys.readouterr().out
    from app.domain_engine.loader import DomainLoader

    assert seen == DomainLoader(REPO_ROOT / "domains").list_domains()
    assert out.startswith("## Busca vetorial (pgvector)")
    assert "very-private-password" not in out


def test_main_prints_domain_errors_on_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
    monkeypatch.setattr(
        ingest,
        "ingest_domain",
        lambda domain, url, chunk_size=800: DomainOutcome(domain.name, error="pgvector ingestion failed"),
    )

    assert ingest.main([]) == EXIT_FAILED
    captured = capsys.readouterr()
    assert "suporte-vps-whatsapp: pgvector ingestion failed" in captured.err


def test_domain_and_all_are_exclusive() -> None:
    with pytest.raises(SystemExit):
        ingest.parse_args(["--domain", "a", "--all"])


def test_script_still_runs_by_path_and_module() -> None:
    text = (REPO_ROOT / "scripts" / "ingest_domain_pgvector.py").read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in text
    assert "raise SystemExit(main())" in text
