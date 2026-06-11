from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import DatabaseUnavailableError
from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime
from app.db.operational import ChatAuditInput, HANDOFF_QUEUED, OperationalRepository
from app.api.schemas.feedback import FeedbackRequest
from scripts.migrate import ledger_exists, verify_applied
from scripts.dispatch_outbox import deliver


def test_persistence_sanitizer_redacts_mixed_sensitive_data() -> None:
    raw = (
        "email=user@example.com ip=192.0.2.10 telefone=+5511999999999 "
        "password=hunter2 Authorization: Bearer token-value-123 "
        "url=https://user:pass@example.com/path?token=secret"
    )

    sanitized = sanitize_for_persistence(raw)

    assert sanitized is not None
    assert "user@example.com" not in sanitized
    assert "192.0.2.10" not in sanitized
    assert "+5511999999999" not in sanitized
    assert "hunter2" not in sanitized
    assert "token-value-123" not in sanitized
    assert "user:pass" not in sanitized
    assert "token=secret" not in sanitized
    assert REDACTION_VERSION == "phase0-v1"


def test_persistence_sanitizer_preserves_non_sensitive_support_text() -> None:
    text = "Como reiniciar o nginx com segurança?"

    assert sanitize_for_persistence(text) == text


def test_payload_sanitizer_rejects_unknown_objects() -> None:
    with pytest.raises(TypeError):
        sanitize_payload({"unsafe": object()})


def test_database_runtime_maps_pool_failure_to_stable_error() -> None:
    class FailingPool:
        @contextmanager
        def connection(self):
            raise RuntimeError("private database detail")
            yield

    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="memory",
    )
    runtime = DatabaseRuntime(settings, pool=FailingPool())

    with pytest.raises(DatabaseUnavailableError, match="database transaction failed"):
        with runtime.transaction():
            pass


def test_migration_verification_rejects_checksum_drift(tmp_path: Path) -> None:
    migration = tmp_path / "001_example.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")

    errors = verify_applied([migration], {"001_example.sql": "wrong-checksum"})

    assert errors == ["checksum mismatch: 001_example.sql"]


def test_migration_status_can_check_missing_ledger_without_creating_it() -> None:
    cursor = RecordingCursor(rows=[(None,)])
    connection = RecordingConnection(cursor)

    assert ledger_exists(connection) is False
    assert all("CREATE TABLE" not in sql for sql, _ in cursor.calls)


def test_migration_runner_has_bounded_connection_timeout() -> None:
    source = Path("scripts/migrate.py").read_text(encoding="utf-8")

    assert "DATABASE_CONNECT_TIMEOUT_SECONDS" in source
    assert "connect_timeout=connect_timeout" in source


def test_phase0_migrations_define_otp_exhausted_and_unique_outbox_key() -> None:
    root = Path(__file__).resolve().parents[1]
    otp_sql = (root / "migrations/003_phase0_otp_status.sql").read_text(encoding="utf-8")
    operational_sql = (
        root / "migrations/004_phase0_operational_foundation.sql"
    ).read_text(encoding="utf-8")

    assert "'exhausted'" in otp_sql
    assert "idempotency_key TEXT NOT NULL UNIQUE" in operational_sql
    assert "FOR UPDATE SKIP LOCKED" not in operational_sql


def test_outbox_delivery_is_signed_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, *, data, headers, timeout):
        captured.update(url=url, data=data, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setenv("HANDOFF_WEBHOOK_URL", "https://internal.example/handoff")
    monkeypatch.setenv("OUTBOX_WEBHOOK_SECRET", "dedicated-secret")
    monkeypatch.setattr("scripts.dispatch_outbox.requests.post", fake_post)

    deliver(
        {
            "event_type": "handoff.requested",
            "request_id": "req-1",
            "idempotency_key": "handoff:req-1",
            "payload_sanitized": {"summary": "safe"},
        }
    )

    headers = captured["headers"]
    assert headers["X-Idempotency-Key"] == "handoff:req-1"
    assert headers["X-Webhook-Signature"].startswith("sha256=")
    assert headers["X-Webhook-Timestamp"]


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = iter(rows)
        self.calls: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self):
        return next(self.rows, None)


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


class RecordingRuntime:
    enabled = True

    def __init__(self, rows: list[object]) -> None:
        self.settings = SimpleNamespace(persistence_hash_secret="persistence-secret")
        self.cursor = RecordingCursor(rows)
        self.connection = RecordingConnection(self.cursor)

    @contextmanager
    def transaction(self):
        yield self.connection


def test_escalated_chat_is_recorded_with_idempotent_outbox_key() -> None:
    runtime = RecordingRuntime(rows=[("domain-id",)])
    repository = OperationalRepository(runtime)

    status = repository.record_chat(
        ChatAuditInput(
            request_id="req-1",
            domain="suporte-vps-whatsapp",
            session_id="raw-session",
            question="meu email user@example.com",
            answer="vou escalar",
            confidence=0.2,
            escalated=True,
            handoff_reasons=["low_confidence"],
            references=["safe.md"],
            error_code=None,
        )
    )

    assert status == HANDOFF_QUEUED
    outbox_params = runtime.cursor.calls[-1][1]
    assert outbox_params is not None
    assert outbox_params[0] == "handoff:req-1"
    assert "user@example.com" not in str(runtime.cursor.calls)


def test_feedback_uses_server_context_instead_of_client_references() -> None:
    runtime = RecordingRuntime(
        rows=[("audit-id", True, ["low_confidence"], ["trusted.md"], None)]
    )
    repository = OperationalRepository(runtime)

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-1",
            helpful=False,
            source="n8n",
            references=["forged.md"],
            handoff_reasons=["forged_reason"],
            escalated=False,
        )
    )

    assert response.storage == "postgres"
    assert response.status == "matched"
    insert_params = runtime.cursor.calls[-1][1]
    assert insert_params is not None
    assert "forged.md" not in str(insert_params)
    assert insert_params[-2] is True
