from typing import Protocol

from app.domain_engine.models import DomainConfig
from app.retrieval.models import RetrievedChunk


class VectorStore(Protocol):
    def search(
        self,
        domain: DomainConfig,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError
