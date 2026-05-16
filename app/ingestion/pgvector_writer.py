from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Protocol

from app.core.config import get_settings
from app.domain_engine.models import DomainConfig
from app.ingestion.models import KnowledgeChunk, KnowledgeDocument


class PgVectorIngestionError(RuntimeError):
    """Raised when domain knowledge cannot be persisted to pgvector."""


class EmbeddingBatchProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class ConnectionFactory(Protocol):
    def __call__(self, database_url: str) -> AbstractContextManager[Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class PgVectorIngestionResult:
    domain: str
    documents: int
    chunks: int
    embedded_chunks: int


class PgVectorIngestionWriter:
    """Persists prepared domain knowledge into the platform pgvector schema."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.database_url = database_url
        self.connection_factory = connection_factory or self._connect

    def persist(
        self,
        *,
        domain: DomainConfig,
        documents: Sequence[KnowledgeDocument],
        chunks: Sequence[KnowledgeChunk],
        embedding_provider: EmbeddingBatchProvider,
    ) -> PgVectorIngestionResult:
        database_url = self.database_url or get_settings().database_url
        if not database_url:
            raise PgVectorIngestionError("DATABASE_URL is required for pgvector ingestion")

        chunk_list = list(chunks)
        embeddings = self._embed_chunks(chunk_list, embedding_provider, domain)
        documents_by_source = {document.source: document for document in documents}
        embedding_by_position = {
            position: embedding for position, embedding in enumerate(embeddings)
        }
        chunks_by_source = self._group_chunks_by_source(chunk_list)

        try:
            with self.connection_factory(database_url) as connection:
                with connection.cursor() as cursor:
                    domain_id = self._upsert_domain(cursor, domain)
                    embedded_chunks = 0

                    for source, source_chunks in chunks_by_source.items():
                        document = documents_by_source.get(source)
                        first_chunk = source_chunks[0][1]
                        title = document.title if document else first_chunk.title
                        content = document.content if document else "\n\n".join(
                            chunk.text for _, chunk in source_chunks
                        )
                        article_id = self._upsert_article(
                            cursor,
                            domain_id=domain_id,
                            title=title,
                            source=source,
                            content=content,
                        )

                        for chunk_position, chunk in source_chunks:
                            embedding = embedding_by_position[chunk_position]
                            self._upsert_chunk(
                                cursor,
                                domain_id=domain_id,
                                article_id=article_id,
                                chunk=chunk,
                                embedding=embedding,
                            )
                            embedded_chunks += 1

                connection.commit()
        except PgVectorIngestionError:
            raise
        except Exception as exc:
            raise PgVectorIngestionError("pgvector ingestion failed") from exc

        return PgVectorIngestionResult(
            domain=domain.name,
            documents=len(documents),
            chunks=len(chunk_list),
            embedded_chunks=embedded_chunks,
        )

    def _connect(self, database_url: str) -> AbstractContextManager[Any]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised when dependency is absent.
            raise PgVectorIngestionError("psycopg is required for pgvector ingestion") from exc

        return psycopg.connect(database_url)

    def _embed_chunks(
        self,
        chunks: Sequence[KnowledgeChunk],
        embedding_provider: EmbeddingBatchProvider,
        domain: DomainConfig,
    ) -> list[list[float]]:
        texts = [chunk.text for chunk in chunks]
        if not texts:
            return []

        embeddings = embedding_provider.embed_documents(texts)
        if len(embeddings) != len(texts):
            raise PgVectorIngestionError("embedding provider returned an unexpected count")

        return [self._normalize_embedding(embedding, domain) for embedding in embeddings]

    def _normalize_embedding(
        self,
        embedding: Sequence[float],
        domain: DomainConfig,
    ) -> list[float]:
        values = [float(value) for value in embedding]
        if len(values) != domain.embedding.dimensions:
            raise PgVectorIngestionError("embedding dimensions do not match domain config")
        if not all(math.isfinite(value) for value in values):
            raise PgVectorIngestionError("embedding contains invalid values")
        return values

    def _upsert_domain(self, cursor: Any, domain: DomainConfig) -> str:
        cursor.execute(
            """
            INSERT INTO domains (name, display_name)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                updated_at = now()
            RETURNING id
            """,
            (domain.name, domain.display_name),
        )
        return str(cursor.fetchone()[0])

    def _upsert_article(
        self,
        cursor: Any,
        *,
        domain_id: str,
        title: str,
        source: str,
        content: str,
    ) -> str:
        cursor.execute(
            """
            INSERT INTO articles (domain_id, title, source, source_type, content_hash, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
            ON CONFLICT (domain_id, source) DO UPDATE
            SET title = EXCLUDED.title,
                content_hash = EXCLUDED.content_hash,
                status = 'active',
                updated_at = now()
            RETURNING id
            """,
            (domain_id, title, source, "markdown", self._content_hash(content)),
        )
        return str(cursor.fetchone()[0])

    def _upsert_chunk(
        self,
        cursor: Any,
        *,
        domain_id: str,
        article_id: str,
        chunk: KnowledgeChunk,
        embedding: Sequence[float],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO article_chunks (
              article_id,
              domain_id,
              chunk_index,
              chunk_text,
              content_hash,
              token_estimate,
              metadata,
              embedding
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
            ON CONFLICT (article_id, chunk_index) DO UPDATE
            SET chunk_text = EXCLUDED.chunk_text,
                content_hash = EXCLUDED.content_hash,
                token_estimate = EXCLUDED.token_estimate,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
            """,
            (
                article_id,
                domain_id,
                chunk.chunk_index,
                chunk.text,
                self._content_hash(chunk.text),
                self._estimate_tokens(chunk.text),
                json.dumps(
                    {
                        "source": chunk.source,
                        "title": chunk.title,
                        "chunk_index": chunk.chunk_index,
                    }
                ),
                self._vector_literal(embedding),
            ),
        )

    def _group_chunks_by_source(
        self,
        chunks: Sequence[KnowledgeChunk],
    ) -> dict[str, list[tuple[int, KnowledgeChunk]]]:
        grouped: dict[str, list[tuple[int, KnowledgeChunk]]] = {}
        for position, chunk in enumerate(chunks):
            grouped.setdefault(chunk.source, []).append((position, chunk))
        return grouped

    def _vector_literal(self, values: Sequence[float]) -> str:
        return "[" + ",".join(str(float(value)) for value in values) + "]"

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text.split()))
