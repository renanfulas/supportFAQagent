from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes import feedback as feedback_route
from app.api.routes import web_chat
from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.api.schemas.web_chat import WebFeedbackRequest
from app.conversations.service import hash_session
from app.core.config import get_settings
from app.core.persistence_sanitize import REDACTED_SECRET, sanitize_for_persistence, sanitize_payload
from app.core.privacy import hash_sensitive_value
from app.core.errors import DatabaseUnavailableError
from app.db.operational import (
    ChatAuditInput,
    FeedbackIntegrityConflictError,
    OperationalRepository,
)
from app.main import create_app


API_KEY_HEADER = {"X-API-Key": "local-dev-api-key"}


@pytest.mark.parametrize(
    ("raw", "forbidden"),
    [
        ("Minha senha \u00e9 swordfish", "swordfish"),
        ("Minha senha do banco \u00e9 bank-secret", "bank-secret"),
        ("Minha senha \u00e9 correct horse battery staple", "horse battery staple"),
        ("The password is correct-horse", "correct-horse"),
        ("Meu IPv6 e 2001:db8::1234", "2001:db8::1234"),
        ("Loopback ::1 deve ser privado", "::1"),
        ("segredo: valor-super-privado", "valor-super-privado"),
        (
            "postgresql://db_admin:db_password@db.internal:5432/supportfaq",
            "db_password",
        ),
        ("redis://:cache-secret@redis.internal:6379/0", "cache-secret"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789AB", "ghp_"),
        ("github_pat_11AA22BB33CC44DD55EE66FF77", "github_pat_"),
        ("AKIA1234567890ABCDEF", "AKIA"),
        ("xoxb-" + "1234567890-" + "abcdefghijklmnop", "xoxb-"),
        ("sk_" + "live_" + "abcdefghijklmnopqrstuvwxyz", "sk_live_"),
        ("AIzaabcdefghijklmnopqrstuvwxyz123456789", "AIza"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjdXN0b21lciJ9.signature123456",
            "eyJhbGci",
        ),
        ("Cookie: session=raw-cookie; csrf=raw-csrf", "raw-cookie"),
        ("prefix Cookie: session=raw-cookie; csrf=raw-csrf", "raw-csrf"),
        ("Set-Cookie: session=raw-cookie; HttpOnly", "raw-cookie"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
        ("X-API-Key: private-api-key-value", "private-api-key-value"),
        ("GITHUB_TOKEN=plain-github-secret", "plain-github-secret"),
        ("AWS_SECRET_ACCESS_KEY=plain-aws-secret", "plain-aws-secret"),
        ('{"Cookie": "arbitrary_name=raw-cookie"}', "raw-cookie"),
        (
            "-----BEGIN PRIVATE KEY-----\nraw-private-key\n-----END PRIVATE KEY-----",
            "raw-private-key",
        ),
    ],
)
def test_persistence_sanitizer_redacts_common_secret_formats(
    raw: str,
    forbidden: str,
) -> None:
    sanitized = sanitize_for_persistence(raw)

    assert sanitized is not None
    assert forbidden not in sanitized
    assert any(
        marker in sanitized
        for marker in (REDACTED_SECRET, "[REDACTED_URL]", "[REDACTED_IP]")
    )


@pytest.mark.parametrize(
    "safe_text",
    [
        "A senha deve ter pelo menos 12 caracteres.",
        "Use secret management e token bucket no desenho.",
        "Consulte https://docs.example.com/nginx?section=cache.",
        "Consulte https://example.com/monkey/status.",
        "O header Content-Type deve ser application/json.",
    ],
)
def test_persistence_sanitizer_avoids_gross_false_positives(safe_text: str) -> None:
    assert sanitize_for_persistence(safe_text) == safe_text


def test_payload_sanitizer_redacts_values_under_sensitive_keys() -> None:
    payload = {
        "headers": {
            "Authorization": "Bearer raw-bearer-token",
            "Set-Cookie": "session=raw-cookie",
        },
        "password": "raw-password",
        "token_count": 4,
        "summary": "Texto seguro.",
    }

    sanitized = sanitize_payload(payload)

    assert sanitized["headers"]["Authorization"] == REDACTED_SECRET
    assert sanitized["headers"]["Set-Cookie"] == REDACTED_SECRET
    assert sanitized["password"] == REDACTED_SECRET
    assert sanitized["token_count"] == 4
    assert sanitized["summary"] == "Texto seguro."


@pytest.mark.parametrize("source", ["web", "api", "n8n", "integration"])
def test_feedback_source_allowlist_is_preserved(source: str) -> None:
    assert FeedbackRequest(helpful=True, source=f" {source.upper()} ").source == source


def test_feedback_source_outside_allowlist_is_normalized_to_other() -> None:
    raw_source = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"

    feedback = FeedbackRequest(helpful=True, source=raw_source)

    assert feedback.source == "other"
    assert raw_source not in feedback.model_dump_json()


@pytest.mark.parametrize(
    ("field", "item"),
    [
        ("handoff_reasons", "x" * 81),
        ("references", "x" * 501),
    ],
)
def test_feedback_context_list_items_have_individual_limits(
    field: str,
    item: str,
) -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(helpful=True, **{field: [item]})


def test_feedback_context_lists_reject_scalar_text() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(helpful=True, handoff_reasons="client-controlled-text")


@pytest.mark.parametrize(
    "unsafe_identifier",
    [
        "user@example.com",
        "192.0.2.10",
        "2001:db8::1234",
        "5511999999999",
        "5511-9999-9999",
        "evolution:5511999999999",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "request id with spaces",
    ],
)
def test_feedback_identifiers_reject_pii_secrets_and_free_text(
    unsafe_identifier: str,
) -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(
            request_id=unsafe_identifier,
            message_id=unsafe_identifier,
            helpful=True,
        )
    with pytest.raises(ValidationError):
        WebFeedbackRequest(request_id=unsafe_identifier, helpful=True)


def test_feedback_identifier_accepts_numeric_leading_uuid() -> None:
    request_id = "12345678-abcd-4abc-8abc-1234567890ab"

    assert FeedbackRequest(request_id=request_id, helpful=True).request_id == request_id
    assert WebFeedbackRequest(request_id=request_id, helpful=True).request_id == request_id


def test_repository_rejects_unsafe_identifier_if_model_validation_is_bypassed() -> None:
    runtime = RecordingRuntime(rows=[])
    repository = OperationalRepository(runtime)
    feedback = FeedbackRequest.model_construct(
        request_id="ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        message_id=None,
        session_id=None,
        helpful=True,
        reason=None,
        comment=None,
        source="api",
        escalated=None,
        handoff_reasons=[],
        references=[],
        error_code=None,
    )

    with pytest.raises(DatabaseUnavailableError, match="feedback sanitization failed"):
        repository.record_feedback(feedback)

    assert runtime.cursor.calls == []


def test_chat_repository_rejects_unsafe_request_id_before_sql_or_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    runtime = RecordingRuntime(rows=[])
    repository = OperationalRepository(runtime)
    monkeypatch.setattr(
        "app.db.operational.log_event",
        lambda _logger, event, **fields: captured.update(event=event, **fields),
    )

    result = repository.record_chat(
        ChatAuditInput(
            request_id="ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
            domain="suporte-vps-whatsapp",
            session_id="session-private",
            question="Pergunta segura",
            answer="Resposta segura",
            confidence=0.8,
            escalated=False,
            handoff_reasons=[],
            references=[],
            error_code=None,
        )
    )

    assert result.persistence_status == "persistence_unavailable"
    assert runtime.cursor.calls == []
    assert captured["request_id"] is None
    assert "ghp_" not in str(captured)


def test_session_log_hash_uses_hmac_when_secret_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PERSISTENCE_HASH_SECRET", raising=False)
    local_hash = hash_sensitive_value("whatsapp:+5511999999999")
    keyed_hash = hash_sensitive_value(
        "whatsapp:+5511999999999",
        secret="private-observability-secret",
    )

    assert local_hash is not None
    assert keyed_hash is not None
    assert keyed_hash != local_hash
    assert keyed_hash == hash_sensitive_value(
        " whatsapp:+5511999999999 ",
        secret="private-observability-secret",
    )


def test_session_log_hash_uses_configured_secret_for_callers_without_explicit_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PERSISTENCE_HASH_SECRET", raising=False)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(persistence_hash_secret="configured-log-secret"),
    )

    assert hash_sensitive_value("session-a") == hash_sensitive_value(
        "session-a",
        secret="configured-log-secret",
    )


def test_feedback_with_session_matches_only_same_session_audit() -> None:
    runtime = RecordingRuntime(
        rows=[("audit-same-session", False, [], ["trusted.md"], None)]
    )
    repository = OperationalRepository(runtime)

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-shared",
            session_id="session-a",
            helpful=True,
            source="web",
        )
    )

    select_sql, select_params = runtime.cursor.calls[0]
    expected_hash = hash_session("session-a", "persistence-secret")
    insert_params = runtime.cursor.calls[-1][1]

    assert response.status == "matched"
    assert "candidate.session_hash = %s" in select_sql
    assert "other.session_hash = candidate.session_hash" in select_sql
    assert select_params == ("req-shared", expected_hash, "hmac-sha256-v1")
    assert insert_params is not None
    assert insert_params[2] == "audit-same-session"
    assert insert_params[3] == expected_hash
    assert insert_params[4] == "hmac-sha256-v1"


def test_feedback_with_unknown_session_is_orphan_instead_of_cross_session_match() -> None:
    runtime = RecordingRuntime(rows=[None])
    repository = OperationalRepository(runtime)

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-owned-by-another-session",
            session_id="session-attacker",
            helpful=False,
            source="web",
        )
    )

    insert_params = runtime.cursor.calls[-1][1]
    assert response.status == "orphan"
    assert insert_params is not None
    assert insert_params[2] is None
    assert insert_params[9] == "orphan"


def test_internal_feedback_without_session_uses_only_globally_unique_audit() -> None:
    runtime = RecordingRuntime(
        rows=[("audit-globally-unique", True, ["low_confidence"], ["trusted.md"], None)]
    )
    repository = OperationalRepository(runtime)

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-internal-unique",
            helpful=False,
            source="n8n",
        )
    )

    select_sql, select_params = runtime.cursor.calls[0]
    insert_params = runtime.cursor.calls[-1][1]

    assert response.status == "matched"
    assert "candidate.session_hash = %s" not in select_sql
    assert "other.id <> candidate.id" in select_sql
    assert select_params == ("req-internal-unique",)
    assert insert_params is not None
    assert insert_params[2] == "audit-globally-unique"
    assert insert_params[3] is None


def test_feedback_reason_and_comment_are_sanitized_before_insert() -> None:
    runtime = RecordingRuntime(rows=[("audit-id", False, [], [], None)])
    repository = OperationalRepository(runtime)

    response = repository.record_feedback(
        FeedbackRequest(
            request_id="req-private-feedback",
            session_id="session-private",
            helpful=False,
            reason="Minha senha \u00e9 reason-secret",
            comment="Use ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
            source="ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        )
    )

    insert_params = runtime.cursor.calls[-1][1]
    assert response.status == "matched"
    assert insert_params is not None
    assert "reason-secret" not in str(insert_params)
    assert "ghp_" not in str(insert_params)
    assert insert_params[6] == f"Minha senha \u00e9 {REDACTED_SECRET}"
    assert insert_params[7] == f"Use {REDACTED_SECRET}"
    assert insert_params[8] == "other"


def test_repository_normalizes_source_even_if_model_validation_is_bypassed() -> None:
    raw_source = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"
    runtime = RecordingRuntime(rows=[])
    repository = OperationalRepository(runtime)
    feedback = FeedbackRequest.model_construct(
        helpful=True,
        source=raw_source,
    )

    response = repository.record_feedback(feedback)

    insert_params = runtime.cursor.calls[-1][1]
    assert response.status == "orphan"
    assert insert_params is not None
    assert insert_params[8] == "other"
    assert raw_source not in str(insert_params)


def test_feedback_with_message_id_is_idempotent_for_same_sanitized_payload() -> None:
    runtime = RecordingRuntime(rows=[])
    repository = OperationalRepository(runtime)
    payload = FeedbackRequest(
        message_id="message-1",
        helpful=True,
        reason="resolved",
        source="n8n",
    )

    first = repository.record_feedback(payload)
    first_params = runtime.cursor.calls[-1][1]
    second = repository.record_feedback(payload)
    second_params = runtime.cursor.calls[-1][1]

    assert first.feedback_id == second.feedback_id == "feedback-id"
    assert first_params is not None
    assert second_params is not None
    assert first_params[1] == "message-1"
    assert first_params[12] == second_params[12]
    assert first_params[13] == second_params[13]
    assert first_params[12] is not None


def test_feedback_idempotency_rejects_same_message_with_different_payload() -> None:
    runtime = RecordingRuntime(rows=[("feedback-id", "orphan", "different-fingerprint")])
    repository = OperationalRepository(runtime)

    with pytest.raises(FeedbackIntegrityConflictError):
        repository.record_feedback(
            FeedbackRequest(
                message_id="message-conflict",
                helpful=False,
                source="n8n",
            )
        )


def test_protected_feedback_log_never_contains_raw_reason_or_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields) -> None:
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setenv("PERSISTENCE_BACKEND", "disabled")
    get_settings.cache_clear()
    monkeypatch.setattr(feedback_route, "log_event", capture_log_event)
    client = TestClient(create_app())

    try:
        response = client.post(
            "/feedback",
            headers=API_KEY_HEADER,
            json={
                "request_id": "req-log-private",
                "helpful": False,
                "reason": "Minha senha e route-secret",
                "comment": "Comentario privado route-comment-secret",
                "source": "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
                "handoff_reasons": ["client-controlled-reason-secret"],
                "error_code": "client-controlled-error-secret",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert captured["event"] == "feedback_recorded"
    assert captured["reason_present"] is True
    assert captured["comment_present"] is True
    assert captured["source"] == "other"
    assert captured["handoff_reason_count"] == 1
    assert captured["error_code_present"] is True
    assert "reason" not in captured
    assert "comment" not in captured
    assert "route-secret" not in str(captured)
    assert "route-comment-secret" not in str(captured)
    assert "client-controlled-reason-secret" not in str(captured)
    assert "client-controlled-error-secret" not in str(captured)
    assert "ghp_" not in str(captured)


def test_protected_feedback_log_uses_hmac_for_session_when_secret_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields) -> None:
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setenv("PERSISTENCE_BACKEND", "disabled")
    monkeypatch.setenv("PERSISTENCE_HASH_SECRET", "route-log-secret")
    get_settings.cache_clear()
    monkeypatch.setattr(feedback_route, "log_event", capture_log_event)
    client = TestClient(create_app())

    try:
        response = client.post(
            "/feedback",
            headers=API_KEY_HEADER,
            json={
                "request_id": "req-hmac-log",
                "session_id": "whatsapp:+5511999999999",
                "helpful": True,
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert captured["session_id_hash"] == hash_sensitive_value(
        "whatsapp:+5511999999999",
        secret="route-log-secret",
    )


def test_unsafe_feedback_request_id_is_rejected_before_route_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(
        feedback_route,
        "log_event",
        lambda *_args, **_kwargs: captured.append("logged"),
    )
    client = TestClient(create_app())

    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={
            "request_id": "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
            "helpful": True,
        },
    )

    assert response.status_code == 422
    assert captured == []


def test_feedback_idempotency_conflict_returns_stable_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def conflict(_self, _payload):
        raise FeedbackIntegrityConflictError("private detail")

    monkeypatch.setattr("app.feedback.service.FeedbackService.record", conflict)
    client = TestClient(create_app())

    response = client.post(
        "/feedback",
        headers=API_KEY_HEADER,
        json={"message_id": "message-conflict", "helpful": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "feedback_idempotency_conflict"
    assert "private detail" not in response.text


def test_web_feedback_log_never_contains_raw_reason_or_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_log_event(_logger, event: str, **fields) -> None:
        captured["event"] = event
        captured.update(fields)

    def fake_record(_self, _payload) -> FeedbackResponse:
        return FeedbackResponse(
            feedback_id="feedback-private",
            accepted=True,
            status="orphan",
            storage="postgres",
        )

    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    monkeypatch.setattr(web_chat, "log_event", capture_log_event)
    monkeypatch.setattr("app.feedback.service.FeedbackService.record", fake_record)
    client = TestClient(create_app())

    try:
        response = client.post(
            "/web/feedback",
            json={
                "request_id": "req-web-private",
                "helpful": False,
                "reason": "Minha senha e web-route-secret",
                "comment": "Comentario privado web-comment-secret",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert captured["event"] == "feedback_recorded"
    assert captured["reason_present"] is True
    assert captured["comment_present"] is True
    assert captured["source"] == "web"
    assert "reason" not in captured
    assert "comment" not in captured
    assert "web-route-secret" not in str(captured)
    assert "web-comment-secret" not in str(captured)


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
