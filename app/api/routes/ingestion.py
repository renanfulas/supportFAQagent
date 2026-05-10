from fastapi import APIRouter, HTTPException

from app.api.schemas.ingestion import IngestionPreviewResponse
from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.ingestion.service import IngestionService


router = APIRouter()


@router.get("/{domain_name}/preview", response_model=IngestionPreviewResponse)
def preview_domain_ingestion(domain_name: str) -> IngestionPreviewResponse:
    settings = get_settings()
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(domain_name)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    service = IngestionService()
    documents = service.load_domain_documents(domain)
    chunks = service.chunk_documents(documents)

    return IngestionPreviewResponse(
        domain=domain.name,
        document_count=len(documents),
        chunk_count=len(chunks),
        sample_chunks=[chunk.text for chunk in chunks[:3]],
    )
