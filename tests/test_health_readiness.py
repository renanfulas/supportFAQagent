from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import DatabaseUnavailableError
from app.health.service import (
    HealthService,
    OUTBOX_OLDEST_READY_DEGRADED_SECONDS_ENV,
    OUTBOX_PROCESSING_STALE_SECONDS_ENV,
    OUTBOX_READY_DEGRADED_COUNT_ENV,
    PGVECTOR_MIN_DOMAIN_EMBEDDINGS_ENV,
)
from app.core.migration_checksum import migration_checksum
from app.main import create_app
from app.api.routes import health


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}


class FailingRuntime:
    pool_enabled = True
    retrieval_enabled = True
    persistence_enabled = True

    @contextmanager
    def transaction(self):
        raise DatabaseUnavailableError("private detail")
        yield


class DisabledRuntime:
    pool_enabled = False
    retrieval_enabled = False
    persistence_enabled = False
    web_auth_enabled = False
    ingress_enabled = False
    settings = SimpleNamespace(default_domain="suporte-vps-whatsapp")


class RecordingCursor:
    def __init__(self, row) -> None:
        self.row = row
        self.sql = ""
        self.params = None

    def execute(self, sql: str, params=None) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


class RecordingConnection:
    @contextmanager
    def cursor(self):
        yield RecordingCursor(None)


class PersistenceRuntime(DisabledRuntime):
    pool_enabled = True
    persistence_enabled = True

    @contextmanager
    def transaction(self):
        yield RecordingConnection()


def test_readiness_preserves_disabled_local_mode_as_ready() -> None:
    snapshot = HealthService(DisabledRuntime()).readiness()

    assert snapshot["status"] == "ok"
    assert snapshot["components"]["database"]["status"] == "disabled"
    assert snapshot["components"]["retrieval"] == {
        "status": "ok",
        "backend": "lexical",
    }


def test_readiness_fails_closed_when_postgres_is_required_but_disabled() -> None:
    runtime = DisabledRuntime()
    runtime.postgres_required = True

    snapshot = HealthService(runtime).readiness()

    assert snapshot["status"] == "unavailable"
    assert snapshot["components"]["database"] == {
        "status": "unavailable",
        "reason": "postgres_required",
    }


def test_readiness_reports_database_failure_without_private_detail() -> None:
    snapshot = HealthService(FailingRuntime()).readiness()

    assert snapshot["status"] == "unavailable"
    assert snapshot["components"]["database"]["status"] == "unavailable"
    assert "private detail" not in str(snapshot)


def test_pgvector_readiness_rejects_missing_or_inactive_configured_domain() -> None:
    runtime = DisabledRuntime()
    runtime.retrieval_enabled = True
    runtime.settings = SimpleNamespace(default_domain="configured-domain")
    service = HealthService(runtime)
    cursor = RecordingCursor((False, 0))

    snapshot = service._retrieval_status(
        cursor,
        {
            "domains": True,
            "articles": True,
            "article_chunks": True,
            "vector": True,
        },
    )

    assert snapshot["status"] == "unavailable"
    assert snapshot["reason"] == "domain_missing_or_inactive"
    assert snapshot["domain"] == "configured-domain"
    assert cursor.params == ("configured-domain", "configured-domain", 1)


def test_pgvector_readiness_requires_active_embeddings_for_configured_domain() -> None:
    runtime = DisabledRuntime()
    runtime.retrieval_enabled = True
    service = HealthService(runtime)
    cursor = RecordingCursor((True, 0))

    snapshot = service._retrieval_status(
        cursor,
        {
            "domains": True,
            "articles": True,
            "article_chunks": True,
            "vector": True,
        },
    )

    rendered = " ".join(cursor.sql.lower().split())
    assert snapshot["status"] == "unavailable"
    assert snapshot["reason"] == "insufficient_domain_embeddings"
    assert snapshot["embedded_chunk_count"] == 0
    assert "domains.name = %s" in rendered
    assert "domains.status = 'active'" in rendered
    assert "articles.status = 'active'" in rendered
    assert "articles.domain_id = domains.id" in rendered
    assert "limit %s" in rendered


def test_pgvector_readiness_uses_configurable_minimum_for_active_domain(
    monkeypatch,
) -> None:
    monkeypatch.setenv(PGVECTOR_MIN_DOMAIN_EMBEDDINGS_ENV, "2")
    runtime = DisabledRuntime()
    runtime.retrieval_enabled = True
    service = HealthService(runtime)

    unavailable = service._retrieval_status(
        RecordingCursor((True, 1)),
        {
            "domains": True,
            "articles": True,
            "article_chunks": True,
            "vector": True,
        },
    )
    ready = service._retrieval_status(
        RecordingCursor((True, 2)),
        {
            "domains": True,
            "articles": True,
            "article_chunks": True,
            "vector": True,
        },
    )

    assert unavailable["status"] == "unavailable"
    assert unavailable["required_embedding_count"] == 2
    assert ready["status"] == "ok"
    assert ready["embedded_chunk_count"] == 2


def test_dead_letter_degrades_outbox_without_marking_it_unavailable() -> None:
    runtime = DisabledRuntime()
    runtime.persistence_enabled = True
    service = HealthService(runtime)
    cursor = RecordingCursor((1, 0, 0, 0, 0))

    snapshot = service._outbox_status(cursor, {"operational_outbox": True})

    assert snapshot["status"] == "degraded"
    assert snapshot["dead_letter_count"] == 1


def test_stuck_processing_degrades_outbox_and_uses_dispatcher_reclaim_window() -> None:
    runtime = DisabledRuntime()
    runtime.persistence_enabled = True
    service = HealthService(runtime)
    cursor = RecordingCursor((0, 0, 0, 1, 301))

    snapshot = service._outbox_status(cursor, {"operational_outbox": True})

    rendered = " ".join(cursor.sql.lower().split())
    assert snapshot["status"] == "degraded"
    assert snapshot["stuck_processing_count"] == 1
    assert snapshot["oldest_stuck_processing_seconds"] == 301
    assert snapshot["processing_stale_seconds"] == 300
    assert "status = 'processing'" in rendered
    assert "locked_at is null" in rendered
    assert cursor.params == (300, 300)


def test_stuck_processing_window_is_shared_with_dispatcher_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv(OUTBOX_PROCESSING_STALE_SECONDS_ENV, "120")
    runtime = DisabledRuntime()
    runtime.persistence_enabled = True
    service = HealthService(runtime)
    cursor = RecordingCursor((0, 0, 0, 1, 121))

    snapshot = service._outbox_status(cursor, {"operational_outbox": True})

    assert snapshot["processing_stale_seconds"] == 120
    assert cursor.params == (120, 120)


def test_outbox_readiness_thresholds_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv(OUTBOX_READY_DEGRADED_COUNT_ENV, "3")
    monkeypatch.setenv(OUTBOX_OLDEST_READY_DEGRADED_SECONDS_ENV, "20")
    runtime = DisabledRuntime()
    runtime.persistence_enabled = True
    service = HealthService(runtime)

    count_degraded = service._outbox_status(
        RecordingCursor((0, 3, 0, 0, 0)),
        {"operational_outbox": True},
    )
    age_degraded = service._outbox_status(
        RecordingCursor((0, 0, 20, 0, 0)),
        {"operational_outbox": True},
    )
    healthy = service._outbox_status(
        RecordingCursor((0, 2, 19, 0, 0)),
        {"operational_outbox": True},
    )

    assert count_degraded["status"] == "degraded"
    assert age_degraded["status"] == "degraded"
    assert healthy["status"] == "ok"
    assert healthy["ready_degraded_count"] == 3
    assert healthy["oldest_ready_degraded_seconds"] == 20


def test_migration_readiness_rejects_missing_persistence_tables() -> None:
    runtime = DisabledRuntime()
    runtime.persistence_enabled = True
    service = HealthService(runtime)
    schema = {
        "ledger": True,
        "domains": True,
        "chat_audits": True,
        "feedback": False,
        "operational_outbox": True,
        "conversations": True,
        "messages": True,
    }

    snapshot = service._migration_status(RecordingCursor(None), schema)

    assert snapshot == {
        "status": "unavailable",
        "reason": "essential_tables_missing",
        "missing_tables": ["feedback"],
    }


def test_migration_readiness_accepts_portable_canonical_checksum(
    tmp_path,
    monkeypatch,
) -> None:
    migration = tmp_path / "001_portable.sql"
    migration.write_bytes(b"SELECT 1;\r\n")
    canonical_checksum = migration_checksum(migration)
    monkeypatch.setattr(
        "app.health.service.MIGRATIONS_DIR",
        tmp_path,
    )
    runtime = DisabledRuntime()
    service = HealthService(runtime)
    cursor = RecordingCursor(None)
    cursor.fetchall = lambda: [(migration.name, canonical_checksum)]

    snapshot = service._migration_status(
        cursor,
        {"ledger": True, "schema_name": "private_schema"},
    )

    assert snapshot == {"status": "ok", "applied_count": 1}
    assert "private_schema" in str(cursor.sql)


def test_readiness_is_unavailable_when_enabled_feature_schema_is_incomplete(
    monkeypatch,
) -> None:
    service = HealthService(PersistenceRuntime())
    schema = {
        "ledger": True,
        "domains": True,
        "chat_audits": True,
        "feedback": False,
        "operational_outbox": True,
        "conversations": True,
        "messages": True,
    }
    monkeypatch.setattr(service, "_schema_snapshot", lambda cursor: schema)
    monkeypatch.setattr(
        service,
        "_outbox_status",
        lambda cursor, current_schema: {"status": "ok"},
    )

    snapshot = service.readiness()

    assert snapshot["status"] == "unavailable"
    assert snapshot["components"]["database"]["status"] == "ok"
    assert snapshot["components"]["migrations"] == {
        "status": "unavailable",
        "reason": "essential_tables_missing",
        "missing_tables": ["feedback"],
    }


def test_required_tables_follow_enabled_postgres_features() -> None:
    runtime = DisabledRuntime()
    runtime.retrieval_enabled = True
    runtime.web_auth_enabled = True
    runtime.ingress_enabled = True
    service = HealthService(runtime)
    schema = {
        "ledger": True,
        "domains": True,
        "articles": True,
        "article_chunks": False,
        "verified_identities": True,
        "web_sessions": False,
        "otp_challenges": True,
        "webhook_ingress_receipts": False,
    }

    snapshot = service._migration_status(RecordingCursor(None), schema)

    assert snapshot["status"] == "unavailable"
    assert snapshot["reason"] == "essential_tables_missing"
    assert snapshot["missing_tables"] == [
        "article_chunks",
        "web_sessions",
        "webhook_ingress_receipts",
    ]


def test_readiness_route_keeps_liveness_contract_and_returns_components(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_BACKEND", "lexical")
    monkeypatch.setenv("PERSISTENCE_BACKEND", "disabled")
    monkeypatch.setenv("WEB_AUTH_STORAGE_BACKEND", "memory")
    get_settings.cache_clear()
    client = TestClient(create_app())

    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/health/ready", headers=API_KEY_HEADER)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert set(response.json()["components"]) == {
        "database",
        "migrations",
        "retrieval",
        "outbox",
        "support_console",
    }
    get_settings.cache_clear()


def test_readiness_route_returns_503_only_for_unavailable_components(
    monkeypatch,
) -> None:
    class FakeHealthService:
        def __init__(self, runtime) -> None:
            _ = runtime

        def readiness(self):
            return {"status": "unavailable", "components": {}}

    monkeypatch.setattr(health, "HealthService", FakeHealthService)
    client = TestClient(create_app())

    response = client.get("/health/ready", headers=API_KEY_HEADER)

    assert response.status_code == 503


def test_readiness_route_is_protected() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 403
