from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


class EmbeddingFunction(Protocol):
    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class PgVectorSearchBackend(Protocol):
    def search_chunks(
        self,
        *,
        domain: DomainConfig,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> Sequence[Mapping[str, Any]]:
        raise NotImplementedError


class PgVectorStore(VectorStore):
    """pgvector adapter that keeps SQL and persistence details out of orchestration."""

    def __init__(
        self,
        *,
        embedding_function: EmbeddingFunction | Callable[[str], Sequence[float]],
        search_backend: PgVectorSearchBackend,
    ) -> None:
        self.embedding_function = embedding_function
        self.search_backend = search_backend

    def search(
        self,
        domain: DomainConfig,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        try:
            query_embedding = self._embed_query(query)
            rows = self.search_backend.search_chunks(
                domain=domain,
                query_embedding=query_embedding,
                top_k=top_k,
            )
            return [self._row_to_chunk(row) for row in rows]
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("pgvector retrieval failed") from exc

    def _embed_query(self, query: str) -> list[float]:
        if hasattr(self.embedding_function, "embed_query"):
            embedding = self.embedding_function.embed_query(query)  # type: ignore[union-attr]
        else:
            embedding = self.embedding_function(query)  # type: ignore[operator]

        values = [float(value) for value in embedding]
        if not values:
            raise RetrievalError("pgvector query embedding is empty")
        return values

    def _row_to_chunk(self, row: Mapping[str, Any]) -> RetrievedChunk:
        source = str(row.get("source") or row.get("id") or "")
        title = str(row.get("title") or row.get("source") or "pgvector chunk")
        text = str(row.get("text") or row.get("chunk_text") or "")
        score = self._normalize_score(row.get("score", row.get("similarity", 0.0)))

        if not source or not text:
            raise RetrievalError("pgvector row is missing required chunk fields")

        return RetrievedChunk(
            source=source,
            title=title,
            text=text,
            score=score,
        )

    def _normalize_score(self, raw_score: Any) -> float:
        score = float(raw_score)
        if score < 0.0:
            return 0.0
        if score > 1.0:
            return 1.0
        return score
