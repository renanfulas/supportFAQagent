from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.ingestion.service import IngestionService


def main(domain_name: str | None = None) -> None:
    settings = get_settings()
    target_domain = domain_name or settings.default_domain
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(target_domain)

    if domain is None:
        raise SystemExit(f"Domain not found: {target_domain}")

    service = IngestionService()
    documents = service.load_domain_documents(domain)
    chunks = service.chunk_documents(documents)

    print(f"domain={domain.name}")
    print(f"documents={len(documents)}")
    print(f"chunks={len(chunks)}")


if __name__ == "__main__":
    main()
