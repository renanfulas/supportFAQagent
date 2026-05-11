from app.domain_engine.models import DomainConfig
from app.ingestion.service import IngestionService
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


class LexicalVectorStore(VectorStore):
    """Temporary retrieval adapter until the official vector store is connected."""

    def __init__(self) -> None:
        self.ingestion_service = IngestionService()

    def search(
        self,
        domain: DomainConfig,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        documents = self.ingestion_service.load_domain_documents(domain)
        chunks = self.ingestion_service.chunk_documents(documents)
        query_terms = {term.lower() for term in query.split() if term.strip()}

        ranked: list[RetrievedChunk] = []
        for chunk in chunks:
            score = self._score_chunk(chunk.text, query_terms)
            if score <= 0:
                continue

            ranked.append(
                RetrievedChunk(
                    source=chunk.source,
                    title=chunk.title,
                    text=chunk.text,
                    score=score,
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _score_chunk(self, text: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.0

        lowered = text.lower()
        matches = sum(1 for term in query_terms if term in lowered)
        return matches / len(query_terms)
