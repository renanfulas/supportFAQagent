from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.core.errors import DatabaseUnavailableError
from app.core.migration_checksum import migration_checksum_variants
from app.db.runtime import DatabaseRuntime
from app.db.schema_contract import CONTRACT_MIGRATION, structural_drift


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DEFAULT_DOMAIN = "suporte-vps-whatsapp"
DEFAULT_PGVECTOR_MIN_DOMAIN_EMBEDDINGS = 1
DEFAULT_OUTBOX_READY_DEGRADED_COUNT = 100
DEFAULT_OUTBOX_OLDEST_READY_DEGRADED_SECONDS = 300
DEFAULT_OUTBOX_PROCESSING_STALE_SECONDS = 300

PGVECTOR_MIN_DOMAIN_EMBEDDINGS_ENV = "HEALTH_PGVECTOR_MIN_DOMAIN_EMBEDDINGS"
OUTBOX_READY_DEGRADED_COUNT_ENV = "HEALTH_OUTBOX_READY_DEGRADED_COUNT"
OUTBOX_OLDEST_READY_DEGRADED_SECONDS_ENV = (
    "HEALTH_OUTBOX_OLDEST_READY_DEGRADED_SECONDS"
)
OUTBOX_PROCESSING_STALE_SECONDS_ENV = "OUTBOX_PROCESSING_STALE_SECONDS"


class HealthService:
    """Builds readiness diagnostics without calling LLM or embedding providers."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def readiness(self) -> dict[str, Any]:
        components: dict[str, dict[str, Any]] = {
            "database": {"status": "disabled"},
            "migrations": {"status": "disabled"},
            "retrieval": self._disabled_or_lexical_retrieval(),
            "outbox": {"status": "disabled"},
        }
        if not self.runtime.pool_enabled:
            if getattr(self.runtime, "postgres_required", False):
                unavailable = {"status": "unavailable", "reason": "postgres_required"}
                components["database"] = unavailable
                components["migrations"] = unavailable
                components["outbox"] = unavailable
                return {"status": "unavailable", "components": components}
            return {"status": "ok", "components": components}

        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    schema = self._schema_snapshot(cursor)
                    components["database"] = {"status": "ok"}
                    components["migrations"] = self._migration_status(cursor, schema)
                    components["retrieval"] = self._retrieval_status(cursor, schema)
                    components["outbox"] = self._outbox_status(cursor, schema)
        except DatabaseUnavailableError:
            components["database"] = {"status": "unavailable"}
            if self.runtime.retrieval_enabled:
                components["retrieval"] = {"status": "unavailable", "backend": "pgvector"}
            if self.runtime.persistence_enabled:
                components["outbox"] = {"status": "unavailable"}
            components["migrations"] = {"status": "unavailable"}

        statuses = {component["status"] for component in components.values()}
        if "unavailable" in statuses:
            overall = "unavailable"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "ok"
        return {"status": overall, "components": components}

    def _disabled_or_lexical_retrieval(self) -> dict[str, Any]:
        if self.runtime.retrieval_enabled:
            return {"status": "unavailable", "backend": "pgvector"}
        return {"status": "ok", "backend": "lexical"}

    def _schema_snapshot(self, cursor: Any) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT
              current_schema(),
              to_regclass(format('%I.%I', current_schema(), 'schema_migrations'))::text,
              to_regclass(format('%I.%I', current_schema(), 'domains'))::text,
              to_regclass(format('%I.%I', current_schema(), 'articles'))::text,
              to_regclass(format('%I.%I', current_schema(), 'operational_outbox'))::text,
              to_regclass(format('%I.%I', current_schema(), 'article_chunks'))::text,
              to_regclass(format('%I.%I', current_schema(), 'chat_audits'))::text,
              to_regclass(format('%I.%I', current_schema(), 'feedback'))::text,
              to_regclass(format('%I.%I', current_schema(), 'conversations'))::text,
              to_regclass(format('%I.%I', current_schema(), 'messages'))::text,
              to_regclass(format('%I.%I', current_schema(), 'verified_identities'))::text,
              to_regclass(format('%I.%I', current_schema(), 'web_sessions'))::text,
              to_regclass(format('%I.%I', current_schema(), 'otp_challenges'))::text,
              to_regclass(format('%I.%I', current_schema(), 'webhook_ingress_receipts'))::text,
              EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')
            """
        )
        (
            schema_name,
            ledger,
            domains,
            articles,
            outbox,
            article_chunks,
            chat_audits,
            feedback,
            conversations,
            messages,
            verified_identities,
            web_sessions,
            otp_challenges,
            webhook_ingress_receipts,
            vector_enabled,
        ) = cursor.fetchone()
        return {
            "schema_name": str(schema_name),
            "ledger": bool(ledger),
            "domains": bool(domains),
            "articles": bool(articles),
            "operational_outbox": bool(outbox),
            "article_chunks": bool(article_chunks),
            "chat_audits": bool(chat_audits),
            "feedback": bool(feedback),
            "conversations": bool(conversations),
            "messages": bool(messages),
            "verified_identities": bool(verified_identities),
            "web_sessions": bool(web_sessions),
            "otp_challenges": bool(otp_challenges),
            "webhook_ingress_receipts": bool(webhook_ingress_receipts),
            "vector": bool(vector_enabled),
        }

    def _migration_status(self, cursor: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not schema["ledger"]:
            return {"status": "unavailable", "reason": "ledger_missing"}
        missing_tables = self._missing_essential_tables(schema)
        if missing_tables:
            return {
                "status": "unavailable",
                "reason": "essential_tables_missing",
                "missing_tables": missing_tables,
            }
        from psycopg import sql

        cursor.execute(
            sql.SQL("SELECT name, checksum FROM {}").format(
                sql.Identifier(schema.get("schema_name", "public"), "schema_migrations")
            )
        )
        applied = dict(cursor.fetchall())
        expected = {
            path.name: migration_checksum_variants(path)
            for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
        }
        pending = set(expected) - set(applied)
        unexpected = set(applied) - set(expected)
        mismatched = {
            name
            for name in set(expected) & set(applied)
            if applied[name] not in expected[name]
        }
        if pending or unexpected or mismatched:
            return {
                "status": "unavailable",
                "pending_count": len(pending),
                "unexpected_count": len(unexpected),
                "checksum_mismatch_count": len(mismatched),
            }
        if CONTRACT_MIGRATION in applied:
            drift = structural_drift(cursor, schema.get("schema_name", "public"))
            if drift:
                return {
                    "status": "unavailable",
                    "reason": "structural_drift",
                    "drift_count": len(drift),
                }
        return {"status": "ok", "applied_count": len(applied)}

    def _retrieval_status(self, cursor: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.runtime.retrieval_enabled:
            return {"status": "ok", "backend": "lexical"}
        if (
            not schema.get("domains")
            or not schema.get("articles")
            or not schema.get("article_chunks")
            or not schema.get("vector")
        ):
            return {"status": "unavailable", "backend": "pgvector"}

        domain = self._configured_domain()
        required_embeddings = _positive_int_env(
            PGVECTOR_MIN_DOMAIN_EMBEDDINGS_ENV,
            DEFAULT_PGVECTOR_MIN_DOMAIN_EMBEDDINGS,
        )
        cursor.execute(
            """
            SELECT
              EXISTS (
                SELECT 1
                FROM domains
                WHERE name = %s
                  AND status = 'active'
              ),
              (
                SELECT count(*)
                FROM (
                  SELECT 1
                  FROM article_chunks AS chunks
                  JOIN articles ON articles.id = chunks.article_id
                  JOIN domains ON domains.id = chunks.domain_id
                  WHERE domains.name = %s
                    AND domains.status = 'active'
                    AND articles.status = 'active'
                    AND articles.domain_id = domains.id
                    AND chunks.embedding IS NOT NULL
                  LIMIT %s
                ) AS qualifying_embeddings
              )
            """,
            (domain, domain, required_embeddings),
        )
        domain_active, embedded_chunk_count = cursor.fetchone()
        if not domain_active:
            return {
                "status": "unavailable",
                "backend": "pgvector",
                "domain": domain,
                "reason": "domain_missing_or_inactive",
                "embedded_chunk_count": 0,
                "required_embedding_count": required_embeddings,
            }

        embedded_chunk_count = int(embedded_chunk_count)
        if embedded_chunk_count < required_embeddings:
            return {
                "status": "unavailable",
                "backend": "pgvector",
                "domain": domain,
                "reason": "insufficient_domain_embeddings",
                "embedded_chunk_count": embedded_chunk_count,
                "required_embedding_count": required_embeddings,
            }
        return {
            "status": "ok",
            "backend": "pgvector",
            "domain": domain,
            "embedded_chunk_count": embedded_chunk_count,
            "required_embedding_count": required_embeddings,
        }

    def _outbox_status(self, cursor: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.runtime.persistence_enabled:
            return {"status": "disabled"}
        if not schema["operational_outbox"]:
            return {"status": "unavailable"}
        processing_stale_seconds = _positive_int_env(
            OUTBOX_PROCESSING_STALE_SECONDS_ENV,
            DEFAULT_OUTBOX_PROCESSING_STALE_SECONDS,
        )
        cursor.execute(
            """
            SELECT
              count(*) FILTER (WHERE status = 'dead_letter'),
              count(*) FILTER (
                WHERE status IN ('pending', 'retryable_failed')
                  AND available_at <= now()
              ),
              COALESCE(
                EXTRACT(EPOCH FROM (
                  now() - min(created_at) FILTER (
                    WHERE status IN ('pending', 'retryable_failed')
                      AND available_at <= now()
                  )
                )),
                0
              ),
              count(*) FILTER (
                WHERE status = 'processing'
                  AND (
                    locked_at IS NULL
                    OR locked_at < now() - (%s * INTERVAL '1 second')
                  )
              ),
              COALESCE(
                EXTRACT(EPOCH FROM (
                  now() - min(COALESCE(locked_at, created_at)) FILTER (
                    WHERE status = 'processing'
                      AND (
                        locked_at IS NULL
                        OR locked_at < now() - (%s * INTERVAL '1 second')
                      )
                  )
                )),
                0
              )
            FROM operational_outbox
            """,
            (
                processing_stale_seconds,
                processing_stale_seconds,
            ),
        )
        (
            dead_letter_count,
            ready_count,
            oldest_ready_seconds,
            stuck_processing_count,
            oldest_stuck_processing_seconds,
        ) = cursor.fetchone()
        ready_degraded_count = _positive_int_env(
            OUTBOX_READY_DEGRADED_COUNT_ENV,
            DEFAULT_OUTBOX_READY_DEGRADED_COUNT,
        )
        oldest_ready_degraded_seconds = _positive_int_env(
            OUTBOX_OLDEST_READY_DEGRADED_SECONDS_ENV,
            DEFAULT_OUTBOX_OLDEST_READY_DEGRADED_SECONDS,
        )
        status = (
            "degraded"
            if dead_letter_count > 0
            or stuck_processing_count > 0
            or ready_count >= ready_degraded_count
            or oldest_ready_seconds >= oldest_ready_degraded_seconds
            else "ok"
        )
        return {
            "status": status,
            "ready_count": int(ready_count),
            "dead_letter_count": int(dead_letter_count),
            "oldest_ready_seconds": int(oldest_ready_seconds),
            "stuck_processing_count": int(stuck_processing_count),
            "oldest_stuck_processing_seconds": int(oldest_stuck_processing_seconds),
            "processing_stale_seconds": processing_stale_seconds,
            "ready_degraded_count": ready_degraded_count,
            "oldest_ready_degraded_seconds": oldest_ready_degraded_seconds,
        }

    def _missing_essential_tables(self, schema: dict[str, Any]) -> list[str]:
        required: set[str] = set()
        if self.runtime.persistence_enabled:
            required.update(
                {
                    "domains",
                    "chat_audits",
                    "feedback",
                    "operational_outbox",
                    "conversations",
                    "messages",
                }
            )
        if self.runtime.retrieval_enabled:
            required.update({"domains", "articles", "article_chunks"})
        if getattr(self.runtime, "web_auth_enabled", False):
            required.update({"verified_identities", "web_sessions", "otp_challenges"})
        if getattr(self.runtime, "ingress_enabled", False):
            required.add("webhook_ingress_receipts")
        return sorted(table for table in required if not schema.get(table))

    def _configured_domain(self) -> str:
        settings = getattr(self.runtime, "settings", None)
        configured = getattr(settings, "default_domain", None)
        domain = configured or os.getenv("DEFAULT_DOMAIN") or DEFAULT_DOMAIN
        return str(domain).strip() or DEFAULT_DOMAIN


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default
