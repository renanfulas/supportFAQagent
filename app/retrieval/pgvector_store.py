from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
import math
from typing import Any, Protocol

from app.core.config import get_settings
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


class ConnectionFactory(Protocol):
    def __call__(self, database_url: str) -> AbstractContextManager[Any]:
        raise NotImplementedError


class PostgresPgVectorSearchBackend(PgVectorSearchBackend):
    """PostgreSQL backend for pgvector retrieval using the platform schema."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.database_url = database_url
        self.connection_factory = connection_factory or self._connect

    def search_chunks(
        self,
        *,
        domain: DomainConfig,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> Sequence[Mapping[str, Any]]:
        database_url = self.database_url or get_settings().database_url
        if not database_url:
            raise RetrievalError("DATABASE_URL is required for pgvector retrieval")

        embedding_literal = self._to_vector_literal(query_embedding, domain)
        safe_top_k = max(1, min(int(top_k), domain.response.max_context_chunks))

        with self.connection_factory(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH resolved_domain AS (
                      SELECT id
                      FROM domains
                      WHERE name = %s
                        AND status = 'active'
                      LIMIT 1
                    )
                    SELECT
                      a.source AS source,
                      a.title AS title,
                      c.chunk_text AS text,
                      1 - (c.embedding <=> %s::vector) AS score
                    FROM article_chunks c
                    JOIN articles a ON a.id = c.article_id
                    WHERE c.domain_id = (SELECT id FROM resolved_domain)
                      AND c.embedding IS NOT NULL
                      AND a.status = 'active'
                    ORDER BY c.embedding <=> %s::vector, c.id
                    LIMIT %s
                    """,
                    (
                        domain.name,
                        embedding_literal,
                        embedding_literal,
                        safe_top_k,
                    ),
                )
                rows = cursor.fetchall()

        return [self._coerce_row(row) for row in rows]

    def _connect(self, database_url: str) -> AbstractContextManager[Any]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised when dependency is absent.
            raise RetrievalError("psycopg is required for pgvector retrieval") from exc

        return psycopg.connect(database_url)

    def _to_vector_literal(
        self,
        query_embedding: Sequence[float],
        domain: DomainConfig,
    ) -> str:
        values = [float(value) for value in query_embedding]
        if not values:
            raise RetrievalError("pgvector query embedding is empty")
        if len(values) != domain.embedding.dimensions:
            raise RetrievalError("pgvector query embedding has invalid dimensions")
        if not all(math.isfinite(value) for value in values):
            raise RetrievalError("pgvector query embedding contains invalid values")

        return "[" + ",".join(str(value) for value in values) + "]"

    def _coerce_row(self, row: Any) -> Mapping[str, Any]:
        if isinstance(row, Mapping):
            return row

        source, title, text, score = row
        return {
            "source": source,
            "title": title,
            "text": text,
            "score": score,
        }


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
