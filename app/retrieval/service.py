from app.domain_engine.models import DomainConfig
from app.ingestion.service import IngestionService
from app.retrieval.models import RetrievedChunk


class RetrievalService:
    """Temporary lexical retrieval until vector storage is added."""

    def __init__(self) -> None:
        self.ingestion_service = IngestionService()

    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        documents = self.ingestion_service.load_domain_documents(domain)
        chunks = self.ingestion_service.chunk_documents(documents)
        question_terms = {term.lower() for term in question.split() if term.strip()}

        ranked: list[RetrievedChunk] = []
        for chunk in chunks:
            score = self._score_chunk(chunk.text, question_terms)
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
        return ranked[: domain.response.max_context_chunks]

    def _score_chunk(self, text: str, question_terms: set[str]) -> float:
        if not question_terms:
            return 0.0

        lowered = text.lower()
        matches = sum(1 for term in question_terms if term in lowered)
        return matches / len(question_terms)
