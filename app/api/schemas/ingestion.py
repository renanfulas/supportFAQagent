from pydantic import BaseModel


class IngestionPreviewResponse(BaseModel):
    domain: str
    document_count: int
    chunk_count: int
    sample_chunks: list[str]
