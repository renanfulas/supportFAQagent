from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    source: str
    title: str
    text: str
    score: float
