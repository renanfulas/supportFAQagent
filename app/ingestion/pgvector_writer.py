"""Persist a domain's knowledge into the platform pgvector schema.

Each run is a sync of the domain's markdown knowledge, safe to repeat:

- articles and chunks are upserted by ``(domain, source)`` and
  ``(article, chunk_index)``, so a rerun never duplicates content;
- a chunk whose text and embedding model did not change keeps its stored
  embedding, so a rerun over unchanged content calls no embedding provider;
- trailing chunks of an article that got shorter are deleted;
- markdown articles that left the client pack are archived (never deleted), so
  retrieval stops returning them. Nothing is archived when the run found no
  chunk at all: an empty or wrongly mounted pack never wipes the base.
"""

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
from app.db.domain_registry import upsert_domain


SOURCE_TYPE = "markdown"


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
    # Chunks whose embedding was computed in this run (new or changed text).
    embedded_chunks: int
    # Unchanged chunks that kept the embedding already stored.
    reused_chunks: int = 0
    # Trailing chunks deleted because their article got shorter.
    removed_chunks: int = 0
    # Markdown articles archived because they left the client pack.
    archived_articles: int = 0


class PgVectorIngestionWriter:
    """Syncs prepared domain knowledge into the platform pgvector schema."""

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
        documents_by_source = {document.source: document for document in documents}
        chunks_by_source = self._group_chunks_by_source(chunk_list)
        model = domain.embedding.model

        try:
            with self.connection_factory(database_url) as connection:
                with connection.cursor() as cursor:
                    domain_id = self._upsert_domain(cursor, domain)
                    stored = self._stored_chunks(cursor, domain_id)
                # Closes the read transaction: no transaction stays open while the
                # embedding provider is called over the network.
                connection.commit()

                pending = [
                    position
                    for position, chunk in enumerate(chunk_list)
                    if stored.get((chunk.source, chunk.chunk_index))
                    != (self._content_hash(chunk.text), model)
                ]
                fresh = self._embed_chunks(
                    [chunk_list[position] for position in pending],
                    embedding_provider,
                    domain,
                )
                embedding_by_position = dict(zip(pending, fresh))

                removed_chunks = 0
                archived_articles = 0
                with connection.cursor() as cursor:
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
                            embedding = embedding_by_position.get(chunk_position)
                            if embedding is None:
                                continue
                            self._upsert_chunk(
                                cursor,
                                domain_id=domain_id,
                                article_id=article_id,
                                chunk=chunk,
                                embedding=embedding,
                                model=model,
                            )

                        removed_chunks += self._delete_trailing_chunks(
                            cursor,
                            article_id=article_id,
                            keep=len(source_chunks),
                        )

                    if chunks_by_source:
                        archived_articles = self._archive_missing_articles(
                            cursor,
                            domain_id=domain_id,
                            sources=list(chunks_by_source),
                        )

                connection.commit()
        except PgVectorIngestionError:
            raise
        except Exception as exc:
            raise PgVectorIngestionError("pgvector ingestion failed") from exc

        return PgVectorIngestionResult(
            domain=domain.name,
            documents=len(documents),
            chunks=len(chunk_list),
            embedded_chunks=len(pending),
            reused_chunks=len(chunk_list) - len(pending),
            removed_chunks=removed_chunks,
            archived_articles=archived_articles,
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

        try:
            embeddings = embedding_provider.embed_documents(texts)
        except PgVectorIngestionError:
            raise
        except Exception as exc:
            # Only the class name: provider messages may echo request details.
            raise PgVectorIngestionError(
                f"embedding provider failed ({type(exc).__name__})"
            ) from exc
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
        return upsert_domain(cursor, name=domain.name, display_name=domain.display_name)

    def _stored_chunks(
        self,
        cursor: Any,
        domain_id: str,
    ) -> dict[tuple[str, int], tuple[str, str | None]]:
        """``(source, chunk_index) -> (content_hash, embedding_model)`` already embedded."""
        cursor.execute(
            """
            SELECT a.source, c.chunk_index, c.content_hash, c.metadata->>'embedding_model'
            FROM article_chunks c
            JOIN articles a ON a.id = c.article_id
            WHERE a.domain_id = %s
              AND a.source_type = %s
              AND c.embedding IS NOT NULL
            """,
            (domain_id, SOURCE_TYPE),
        )
        return {
            (str(source), int(index)): (str(content_hash), model)
            for source, index, content_hash, model in cursor.fetchall()
        }

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
            (domain_id, title, source, SOURCE_TYPE, self._content_hash(content)),
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
        model: str,
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
                        "embedding_model": model,
                    }
                ),
                self._vector_literal(embedding),
            ),
        )

    def _delete_trailing_chunks(self, cursor: Any, *, article_id: str, keep: int) -> int:
        cursor.execute(
            "DELETE FROM article_chunks WHERE article_id = %s AND chunk_index >= %s",
            (article_id, keep),
        )
        return self._rowcount(cursor)

    def _archive_missing_articles(
        self,
        cursor: Any,
        *,
        domain_id: str,
        sources: list[str],
    ) -> int:
        cursor.execute(
            """
            UPDATE articles
            SET status = 'archived',
                updated_at = now()
            WHERE domain_id = %s
              AND source_type = %s
              AND status = 'active'
              AND NOT (source = ANY(%s))
            """,
            (domain_id, SOURCE_TYPE, sources),
        )
        return self._rowcount(cursor)

    def _rowcount(self, cursor: Any) -> int:
        count = getattr(cursor, "rowcount", 0)
        return count if isinstance(count, int) and count > 0 else 0

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
