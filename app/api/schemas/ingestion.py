from pydantic import BaseModel, Field, field_validator


class IngestionPreviewDocument(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    source: str | None = Field(default=None, max_length=240)

    @field_validator("title", "content")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field cannot be blank")
        return normalized

    @field_validator("source")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None


class IngestionPreviewRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=80)
    documents: list[IngestionPreviewDocument] = Field(min_length=1, max_length=20)
    chunk_size: int = Field(default=800, ge=200, le=2000)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("domain cannot be blank")
        return normalized


class IngestionPreviewChunk(BaseModel):
    source: str
    title: str
    text: str
    chunk_index: int


class IngestionPreviewResponse(BaseModel):
    request_id: str | None = None
    domain: str
    document_count: int
    chunk_count: int
    sample_chunks: list[str]
    chunks: list[IngestionPreviewChunk] = Field(default_factory=list)
