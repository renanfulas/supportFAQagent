from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas.ingestion import (
    IngestionPreviewChunk,
    IngestionPreviewRequest,
    IngestionPreviewResponse,
)
from app.core.config import get_settings
from app.core.request_context import get_request_id
from app.core.security import verify_api_key
from app.domain_engine.loader import DomainLoader
from app.ingestion.models import KnowledgeDocument
from app.ingestion.service import IngestionService


router = APIRouter()


@router.post("/preview", response_model=IngestionPreviewResponse)
def preview_payload_ingestion(
    payload: IngestionPreviewRequest,
    request: Request,
    _: str = Depends(verify_api_key),
) -> IngestionPreviewResponse:
    settings = get_settings()
    loader = DomainLoader(settings.domains_path)
    domain = loader.load(payload.domain)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    documents = [
        KnowledgeDocument(
            source=document.source or f"payload:{index}",
            title=document.title,
            content=document.content,
        )
        for index, document in enumerate(payload.documents, start=1)
    ]

    service = IngestionService()
    chunks = service.chunk_documents(documents, chunk_size=payload.chunk_size)

    return IngestionPreviewResponse(
        request_id=get_request_id(request),
        domain=domain.name,
        document_count=len(documents),
        chunk_count=len(chunks),
        sample_chunks=[chunk.text for chunk in chunks[:3]],
        chunks=[
            IngestionPreviewChunk(
                source=chunk.source,
                title=chunk.title,
                text=chunk.text,
                chunk_index=chunk.chunk_index,
            )
            for chunk in chunks
        ],
    )


@router.get("/{domain_name}/preview", response_model=IngestionPreviewResponse)
def preview_domain_ingestion(
    domain_name: str,
    _: str = Depends(verify_api_key),
) -> IngestionPreviewResponse:
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
        chunks=[
            IngestionPreviewChunk(
                source=chunk.source,
                title=chunk.title,
                text=chunk.text,
                chunk_index=chunk.chunk_index,
            )
            for chunk in chunks
        ],
    )
