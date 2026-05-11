from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


class RetrievalService:
    """Retrieval facade for the current store adapter."""

    def __init__(self, vector_store: VectorStore | None = None) -> None:
        self.vector_store = vector_store or LexicalVectorStore()

    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        try:
            return self.vector_store.search(
                domain=domain,
                query=question,
                top_k=domain.response.max_context_chunks,
            )
        except Exception as exc:
            raise RetrievalError("retrieval failed") from exc
