from app.domain_engine.models import DomainConfig
from app.retrieval.models import RetrievedChunk


def compute_confidence(domain: DomainConfig, chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0

    average_score = sum(chunk.score for chunk in chunks) / len(chunks)
    return min(1.0, round(average_score, 2))
