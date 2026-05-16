import argparse

from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.ingestion.pgvector_writer import PgVectorIngestionWriter
from app.ingestion.service import IngestionService
from app.retrieval.embeddings import get_domain_embeddings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist local domain knowledge into PostgreSQL/pgvector.",
    )
    parser.add_argument("--domain", default=None, help="Domain name to ingest.")
    parser.add_argument("--chunk-size", type=int, default=800, help="Chunk size for ingestion.")
    args = parser.parse_args()

    settings = get_settings()
    target_domain = args.domain or settings.default_domain
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(target_domain)

    if domain is None:
        raise SystemExit(f"Domain not found: {target_domain}")

    service = IngestionService()
    documents = service.load_domain_documents(domain)
    chunks = service.chunk_documents(documents, chunk_size=args.chunk_size)

    writer = PgVectorIngestionWriter(database_url=settings.database_url)
    result = writer.persist(
        domain=domain,
        documents=documents,
        chunks=chunks,
        embedding_provider=get_domain_embeddings(domain),
    )

    print(f"domain={result.domain}")
    print(f"documents={result.documents}")
    print(f"chunks={result.chunks}")
    print(f"embedded_chunks={result.embedded_chunks}")


if __name__ == "__main__":
    main()
