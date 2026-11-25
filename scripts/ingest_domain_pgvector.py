"""Sync a domain's knowledge (or the whole client pack) into PostgreSQL/pgvector.

    python -m scripts.ingest_domain_pgvector                 # DEFAULT_DOMAIN
    python -m scripts.ingest_domain_pgvector --domain <name>
    python -m scripts.ingest_domain_pgvector --all [--markdown]

Safe to repeat: unchanged chunks keep their embedding (no provider call), chunks
that left an article are deleted and articles that left the pack are archived
(see ``app/ingestion/pgvector_writer.py``). The embedding provider is only
created when some chunk really needs a new embedding.

Output never carries secrets, the database URL or provider error messages: one
``key=value`` block per domain, or a Markdown section with ``--markdown`` (used
by ``deploy/install.sh`` in the installation report).

Exit codes: 0 ok; 1 a domain failed; 2 invalid configuration (no DATABASE_URL,
unknown domain, missing embedding key); 3 everything synced, but the default
domain has no chunk, so ``RETRIEVAL_BACKEND=pgvector`` would fail readiness.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import sys
from typing import Any, Callable

from app.ingestion.pgvector_writer import PgVectorIngestionError, PgVectorIngestionResult


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_DEFAULT_EMPTY = 3


class EmbeddingConfigError(RuntimeError):
    """The domain's embedding provider cannot be created (missing key, unknown provider)."""


@dataclass
class DomainOutcome:
    name: str
    result: PgVectorIngestionResult | None = None
    error: str | None = None
    config_error: bool = False


class LazyEmbeddings:
    """Creates the domain's embedding provider on the first real embedding call."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._provider: Any = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._provider is None:
            try:
                self._provider = self._factory()
            except (RuntimeError, ValueError, ImportError) as exc:
                raise EmbeddingConfigError(str(exc)) from exc
        return self._provider.embed_documents(texts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync local domain knowledge into PostgreSQL/pgvector.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--domain", default=None, help="Domain name to ingest (default: DEFAULT_DOMAIN).")
    target.add_argument("--all", action="store_true", help="Ingest every domain of the client pack.")
    parser.add_argument("--chunk-size", type=int, default=800, help="Chunk size for ingestion.")
    parser.add_argument("--markdown", action="store_true", help="Print a Markdown report section.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        print(
            "ingest: configuration is invalid; run python -m scripts.config_validate for every reason",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if not getattr(settings, "database_url", None):
        print("ingest: DATABASE_URL is required for pgvector ingestion", file=sys.stderr)
        return EXIT_CONFIG

    from app.domain_engine.loader import DomainLoader

    loader = DomainLoader(settings.domains_path)
    names = loader.list_domains() if args.all else [args.domain or settings.default_domain]
    domains = []
    for name in names:
        domain = loader.load(name)
        if domain is None:
            print(f"ingest: domain not found or invalid: {name}", file=sys.stderr)
            return EXIT_CONFIG
        domains.append(domain)
    if not domains:
        print("ingest: no domain found in the client pack", file=sys.stderr)
        return EXIT_CONFIG

    outcomes = [ingest_domain(domain, settings.database_url, chunk_size=args.chunk_size) for domain in domains]
    status = exit_status(outcomes, default_domain=settings.default_domain)
    output = render_markdown(outcomes, status, settings.default_domain) if args.markdown else render_plain(outcomes)
    sys.stdout.write(output)
    sys.stdout.flush()
    for outcome in outcomes:
        if outcome.error:
            print(f"ingest: {outcome.name}: {outcome.error}", file=sys.stderr)
    return status


def ingest_domain(
    domain: Any,
    database_url: str,
    *,
    chunk_size: int = 800,
    writer: Any = None,
    embeddings_factory: Callable[[Any], Any] | None = None,
) -> DomainOutcome:
    from app.ingestion.pgvector_writer import PgVectorIngestionWriter
    from app.ingestion.service import IngestionService

    if embeddings_factory is None:
        from app.retrieval.embeddings import get_domain_embeddings

        embeddings_factory = get_domain_embeddings

    service = IngestionService()
    documents = service.load_domain_documents(domain)
    chunks = service.chunk_documents(documents, chunk_size=chunk_size)
    writer = writer or PgVectorIngestionWriter(database_url=database_url)
    try:
        result = writer.persist(
            domain=domain,
            documents=documents,
            chunks=chunks,
            embedding_provider=LazyEmbeddings(lambda: embeddings_factory(domain)),
        )
    except PgVectorIngestionError as error:
        cause = error.__cause__
        if isinstance(cause, EmbeddingConfigError):
            return DomainOutcome(
                domain.name,
                error=f"embedding provider '{domain.embedding.provider}' is not configured: {cause}",
                config_error=True,
            )
        return DomainOutcome(domain.name, error=str(error))
    return DomainOutcome(domain.name, result=result)


def exit_status(outcomes: list[DomainOutcome], *, default_domain: str) -> int:
    if any(outcome.config_error for outcome in outcomes):
        return EXIT_CONFIG
    if any(outcome.error for outcome in outcomes):
        return EXIT_FAILED
    default = next((outcome for outcome in outcomes if outcome.name == default_domain), None)
    if default is not None and default.result is not None and default.result.chunks == 0:
        return EXIT_DEFAULT_EMPTY
    return EXIT_OK


def render_plain(outcomes: list[DomainOutcome]) -> str:
    lines: list[str] = []
    for outcome in outcomes:
        lines.append(f"domain={outcome.name}")
        if outcome.result is None:
            lines.append("status=failed")
            continue
        result = outcome.result
        lines += [
            f"documents={result.documents}",
            f"chunks={result.chunks}",
            f"embedded_chunks={result.embedded_chunks}",
            f"reused_chunks={result.reused_chunks}",
            f"removed_chunks={result.removed_chunks}",
            f"archived_articles={result.archived_articles}",
        ]
    return "\n".join(lines) + "\n"


_VERDICT = {
    EXIT_OK: "✅ base sincronizada",
    EXIT_DEFAULT_EMPTY: "⚠️ sincronizada, mas o dominio padrao nao tem conteudo",
    EXIT_FAILED: "❌ falhou",
    EXIT_CONFIG: "❌ configuracao incompleta",
}


def render_markdown(outcomes: list[DomainOutcome], status: int, default_domain: str) -> str:
    lines = [
        "## Busca vetorial (pgvector)",
        "",
        f"- Resultado: {_VERDICT[status]}",
        f"- Dominio padrao: `{default_domain}`",
        "",
        "| Dominio | Documentos | Chunks | Embeddings novos | Reaproveitados | Removidos | Arquivados |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in outcomes:
        if outcome.result is None:
            lines.append(f"| `{outcome.name}` | ❌ {_cell(outcome.error or 'failed')} | | | | | |")
            continue
        r = outcome.result
        lines.append(
            f"| `{outcome.name}` | {r.documents} | {r.chunks} | {r.embedded_chunks} | "
            f"{r.reused_chunks} | {r.removed_chunks} | {r.archived_articles} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
