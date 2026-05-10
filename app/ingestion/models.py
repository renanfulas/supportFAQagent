from pydantic import BaseModel


class KnowledgeDocument(BaseModel):
    source: str
    title: str
    content: str


class KnowledgeChunk(BaseModel):
    source: str
    title: str
    text: str
    chunk_index: int
