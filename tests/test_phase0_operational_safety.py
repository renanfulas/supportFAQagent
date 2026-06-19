from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.core.errors import DatabaseUnavailableError
from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_QUEUED,
    HANDOFF_UNAVAILABLE,
    PERSISTENCE_PERSISTED,
    OperationalRepository,
)
from app.api.schemas.feedback import FeedbackRequest
from scripts.migrate import ledger_exists, verify_applied
from scripts.dispatch_outbox import (
    PermanentDeliveryError,
    deliver,
    deliver_meta_whatsapp,
    resolve_delivery_route,
    resolve_delivery_transport,
)
from scripts.check_readiness import main as check_readiness


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


def test_database_runtime_closes_pool_when_initial_wait_fails(monkeypatch) -> None:
    created = []

    class FailingOpeningPool:
        def __init__(self, **kwargs) -> None:
            self.closed = False
            created.append(self)

        def wait(self, **kwargs) -> None:
            raise RuntimeError("private startup failure")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules,
        "psycopg_pool",
        SimpleNamespace(ConnectionPool=FailingOpeningPool),
    )
    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="memory",
        enable_outbox_ingress=False,
        retrieval_backend="lexical",
        database_url="postgresql://private",
        database_pool_min_size=1,
        database_pool_max_size=2,
        database_connect_timeout_seconds=1,
        database_query_timeout_seconds=1,
    )
    runtime = DatabaseRuntime(settings)

    with pytest.raises(DatabaseUnavailableError, match="database pool unavailable"):
        runtime.open()

    assert created[0].closed is True
    assert runtime._pool is None


def test_migration_verification_rejects_checksum_drift(tmp_path: Path) -> None:
    migration = tmp_path / "001_example.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")

    errors = verify_applied([migration], {"001_example.sql": "wrong-checksum"})

    assert errors == ["checksum mismatch: 001_example.sql"]


def test_migration_status_can_check_missing_ledger_without_creating_it() -> None:
    cursor = RecordingCursor(rows=[("public",), (None,)])
    connection = RecordingConnection(cursor)

    assert ledger_exists(connection) is False
    assert all("CREATE TABLE" not in sql for sql, _ in cursor.calls)


def test_migration_runner_has_bounded_connection_timeout() -> None:
    source = Path("scripts/migrate.py").read_text(encoding="utf-8")

    assert "DATABASE_CONNECT_TIMEOUT_SECONDS" in source
    assert "connect_timeout=connect_timeout" in source


def test_readiness_command_sanitizes_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "scripts.check_readiness.get_settings",
        lambda: (_ for _ in ()).throw(ValueError("private-secret")),
    )

    assert check_readiness() == 1
    output = capsys.readouterr()
    assert "private-secret" not in output.err
    assert "readiness check failed" in output.err


def test_outbox_dispatcher_has_bounded_database_timeouts_and_shared_stale_window() -> None:
    source = Path("scripts/dispatch_outbox.py").read_text(encoding="utf-8")

    assert "DATABASE_CONNECT_TIMEOUT_SECONDS" in source
    assert "DATABASE_QUERY_TIMEOUT_SECONDS" in source
    assert "OUTBOX_PROCESSING_STALE_SECONDS" in source
    assert "connect_timeout=connect_timeout" in source
    assert "statement_timeout" in source


def test_phase0_migrations_define_otp_exhausted_and_unique_outbox_key() -> None:
    root = Path(__file__).resolve().parents[1]
    otp_sql = (root / "migrations/003_phase0_otp_status.sql").read_text(encoding="utf-8")
    operational_sql = (
        root / "migrations/004_phase0_operational_foundation.sql"
    ).read_text(encoding="utf-8")
    ingress_sql = (root / "migrations/005_phase0_webhook_ingress.sql").read_text(
        encoding="utf-8"
    )
    feedback_integrity_sql = (
        root / "migrations/008_feedback_integrity.sql"
    ).read_text(encoding="utf-8")

    assert "'exhausted'" in otp_sql
    assert "idempotency_key TEXT NOT NULL UNIQUE" in operational_sql
    assert "FOR UPDATE SKIP LOCKED" not in operational_sql
    assert "idempotency_key_hash TEXT PRIMARY KEY" in ingress_sql
    assert "payload_hash TEXT NOT NULL" in ingress_sql
    assert "session_hash_version TEXT" in feedback_integrity_sql
    assert "message_id TEXT" in feedback_integrity_sql
    assert "feedback_fingerprint TEXT" in feedback_integrity_sql
    assert "set_legacy_session_hash_version" in feedback_integrity_sql
    assert "chat_audits_legacy_hash_version" in feedback_integrity_sql
    assert "feedback_legacy_hash_version" in feedback_integrity_sql
    assert "idx_chat_audits_feedback_context" in feedback_integrity_sql
    assert "idx_feedback_idempotency_key" in feedback_integrity_sql


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


def test_outbox_event_resolves_to_delivery_route() -> None:
    route = resolve_delivery_route("handoff.requested")

    assert route.name == "handoff"
    assert route.url_env == "HANDOFF_WEBHOOK_URL"
    assert route.transport_env == "OUTBOX_HANDOFF_DELIVERY_TRANSPORT"


def test_outbox_rejects_unknown_event_without_default_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setenv("HANDOFF_WEBHOOK_URL", "https://internal.example/handoff")
    monkeypatch.setenv("OUTBOX_WEBHOOK_SECRET", "dedicated-secret")
    monkeypatch.setattr("scripts.dispatch_outbox.requests.post", fake_post)

    with pytest.raises(PermanentDeliveryError, match="unsupported event type"):
        deliver(
            {
                "event_type": "unknown.event",
                "request_id": "req-unknown",
                "idempotency_key": "unknown:req",
                "payload_sanitized": {"summary": "safe"},
            }
        )

    assert called is False


def test_outbox_disabled_delivery_transport_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = resolve_delivery_route("handoff.requested")
    monkeypatch.setenv(route.transport_env, "disabled")

    assert resolve_delivery_transport(route) == "disabled"
    with pytest.raises(PermanentDeliveryError, match="delivery route is disabled"):
        deliver(
            {
                "event_type": "handoff.requested",
                "request_id": "req-disabled",
                "idempotency_key": "handoff:req-disabled",
                "payload_sanitized": {"summary": "safe"},
            }
        )


def test_outbox_unsupported_delivery_transport_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = resolve_delivery_route("handoff.requested")
    monkeypatch.setenv(route.transport_env, "unknown_transport")

    with pytest.raises(PermanentDeliveryError, match="unsupported delivery transport"):
        resolve_delivery_transport(route)


def test_outbox_rejects_meta_whatsapp_transport_outside_message_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = resolve_delivery_route("handoff.requested")
    monkeypatch.setenv(route.transport_env, "meta_whatsapp")

    with pytest.raises(PermanentDeliveryError, match="not supported for route"):
        deliver(
            {
                "event_type": "handoff.requested",
                "request_id": "req-meta-handoff",
                "idempotency_key": "handoff:req-meta-handoff",
                "payload_sanitized": {"summary": "safe"},
            }
        )


def test_outbox_meta_whatsapp_delivery_sends_text_without_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        def send_text(self, *, to: str, text: str) -> None:
            captured["to"] = to
            captured["text"] = text

    monkeypatch.setenv("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT", "meta_whatsapp")
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "meta-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("META_WHATSAPP_GRAPH_API_VERSION", "v25.0")
    monkeypatch.delenv("OUTBOX_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("scripts.dispatch_outbox.MetaWhatsAppClient", FakeClient)

    deliver(
        {
            "event_type": "whatsapp.message.requested",
            "request_id": "req-meta-message",
            "idempotency_key": "whatsapp:req-meta-message",
            "payload_sanitized": {"to": "5511999999999", "text": "Resposta segura."},
        }
    )

    assert captured["client_kwargs"]["access_token"] == "meta-token"
    assert captured["client_kwargs"]["phone_number_id"] == "phone-id"
    assert captured["to"] == "5511999999999"
    assert captured["text"] == "Resposta segura."


def test_outbox_meta_whatsapp_requires_explicit_payload_shape() -> None:
    route = resolve_delivery_route("whatsapp.message.requested")

    with pytest.raises(PermanentDeliveryError, match="field is required: text"):
        deliver_meta_whatsapp(
            event={
                "event_type": "whatsapp.message.requested",
                "request_id": "req-meta-missing-text",
                "idempotency_key": "whatsapp:req-meta-missing-text",
                "payload_sanitized": {"to": "5511999999999", "body": "ambiguous"},
            },
            route=route,
        )


def test_outbox_treats_non_retryable_4xx_as_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 400

        def raise_for_status(self) -> None:
            import requests

            raise requests.HTTPError("bad request", response=self)

    monkeypatch.setenv("HANDOFF_WEBHOOK_URL", "https://internal.example/handoff")
    monkeypatch.setenv("OUTBOX_WEBHOOK_SECRET", "dedicated-secret")
    monkeypatch.setattr(
        "scripts.dispatch_outbox.requests.post",
        lambda *args, **kwargs: Response(),
    )

    with pytest.raises(PermanentDeliveryError):
        deliver(
            {
                "event_type": "handoff.requested",
                "request_id": "req-permanent",
                "idempotency_key": "handoff:req-permanent",
                "payload_sanitized": {"summary": "safe"},
            }
        )


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple | None]] = []
        self.last_sql = ""
        self.last_params: tuple | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, params))
        self.last_sql = sql
        self.last_params = params

    def fetchone(self):
        if self.rows:
            return self.rows.pop(0)
        if "RETURNING id, context_status, feedback_fingerprint" in self.last_sql:
            assert self.last_params is not None
            return ("feedback-id", self.last_params[9], self.last_params[13])
        return None


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


class RecordingRuntime:
    enabled = True
    persistence_enabled = True

    def __init__(self, rows: list[object]) -> None:
        self.settings = SimpleNamespace(
            persistence_hash_secret="persistence-secret",
            persistence_hash_version="hmac-sha256-v1",
        )
        self.cursor = RecordingCursor(rows)
        self.connection = RecordingConnection(self.cursor)

    @contextmanager
    def transaction(self):
        yield self.connection


def test_escalated_chat_is_recorded_with_idempotent_outbox_key() -> None:
    runtime = RecordingRuntime(
        rows=[
            ("domain-id",),
            (False,),
            ("audit-id", "turn-id"),
            ("conversation-id",),
            ("pending",),
        ]
    )
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
            references=["https://example.com/help?token=reference-secret"],
            error_code="ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        )
    )

    assert status.handoff_status == HANDOFF_QUEUED
    assert status.persistence_status == PERSISTENCE_PERSISTED
    assert status.turn_id == "turn-id"
    outbox_params = runtime.cursor.calls[-1][1]
    assert outbox_params is not None
    assert outbox_params[0] == "handoff:turn-id"
    assert "user@example.com" not in str(runtime.cursor.calls)
    assert "reference-secret" not in str(runtime.cursor.calls)
    assert "ghp_" not in str(runtime.cursor.calls)


@pytest.mark.parametrize("outbox_row", [("dead_letter",), None])
def test_escalated_chat_is_unavailable_when_outbox_is_dead_or_missing(
    outbox_row: tuple[str] | None,
) -> None:
    rows: list[object] = [
        ("domain-id",),
        (False,),
        ("audit-id", "turn-id"),
        ("conversation-id",),
    ]
    if outbox_row is not None:
        rows.append(outbox_row)
    runtime = RecordingRuntime(rows=rows)
    repository = OperationalRepository(runtime)

    status = repository.record_chat(
        ChatAuditInput(
            request_id="req-dead-letter",
            domain="suporte-vps-whatsapp",
            session_id="raw-session",
            question="preciso de ajuda",
            answer="vou escalar",
            confidence=0.2,
            escalated=True,
            handoff_reasons=["low_confidence"],
            references=[],
            error_code=None,
        )
    )

    assert status.handoff_status == HANDOFF_UNAVAILABLE
    assert status.persistence_status == PERSISTENCE_PERSISTED


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
    assert insert_params[10] is True


def test_request_fingerprint_distinguishes_redacted_secrets_without_storing_them() -> None:
    runtime = RecordingRuntime(rows=[])
    repository = OperationalRepository(runtime)
    common = dict(
        request_id="req-shared",
        domain="suporte-vps-whatsapp",
        session_id="session",
        answer="safe",
        confidence=0.8,
        escalated=False,
        handoff_reasons=[],
        references=[],
        error_code=None,
    )
    first = ChatAuditInput(question="password=first-secret", **common)
    second = ChatAuditInput(question="password=second-secret", **common)

    first_fingerprint = repository._request_fingerprint(
        audit=first,
        session_hash=repository._hash(first.session_id),
    )
    second_fingerprint = repository._request_fingerprint(
        audit=second,
        session_hash=repository._hash(second.session_id),
    )

    assert first_fingerprint != second_fingerprint
    assert "first-secret" not in first_fingerprint
    assert "second-secret" not in second_fingerprint
