from app.domain_engine.models import DomainConfig
from app.retrieval.models import RetrievedChunk


def compute_confidence(domain: DomainConfig, chunks: list[RetrievedChunk]) -> float:
    _ = domain
    if not chunks:
        return 0.0

    scores = [chunk.score for chunk in chunks]
    average_score = sum(scores) / len(scores)
    strongest_score = max(scores)

    # Weight the strongest retrieved chunk more heavily so one clearly relevant
    # hit is not drowned out by weaker lexical matches.
    weighted_score = (strongest_score * 0.65) + (average_score * 0.35)
    return min(1.0, round(weighted_score, 2))
