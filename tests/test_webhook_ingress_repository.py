"""Coverage for the WebhookIngressRepository claim/mark transaction logic.

The repository talks to PostgreSQL through ``runtime.transaction()``. These
tests substitute a scripted fake connection/cursor so every claim branch and the
``_mark`` helpers run without a database or network.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.integrations.webhook_ingress import (
    CLAIMED,
    DUPLICATE,
    IN_PROGRESS,
    PAYLOAD_CONFLICT,
    PROCESSING_STALE_SECONDS,
    WebhookIngressRepository,
    idempotency_hash,
    payload_hash,
    verify_signature,
)


class FakeCursor:
    """Cursor whose ``fetchone`` results are scripted in order."""

    def __init__(self, fetch_results: list[object]) -> None:
        self._fetch_results = list(fetch_results)
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> object:
        return self._fetch_results.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._connection = FakeConnection(cursor)
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield self._connection


def _repo(fetch_results: list[object]) -> tuple[WebhookIngressRepository, FakeCursor, FakeRuntime]:
    cursor = FakeCursor(fetch_results)
    runtime = FakeRuntime(cursor)
    return WebhookIngressRepository(runtime), cursor, runtime


def test_claim_inserts_new_receipt_when_absent() -> None:
    repo, cursor, runtime = _repo([None])

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="handoff:req-1",
        request_id="req-1",
        body_hash="bodyhash",
    )

    assert result.status == CLAIMED
    assert result.attempt_count == 1
    assert runtime.transactions == 1
    # First SELECT carries the stale-window seconds; then an INSERT runs.
    select_sql, select_params = cursor.executed[0]
    assert "FOR UPDATE" in select_sql
    assert select_params[0] == PROCESSING_STALE_SECONDS
    assert "INSERT INTO webhook_ingress_receipts" in cursor.executed[1][0]
    # The raw idempotency key is hashed before it reaches SQL.
    assert "handoff:req-1" not in select_sql
    assert idempotency_hash("handoff:req-1") in {p for _, params in cursor.executed for p in params}


def test_claim_detects_payload_conflict_on_event_mismatch() -> None:
    # row = (event_type, payload_hash, status, attempt_count, stale_flag)
    repo, _cursor, _runtime = _repo([("other.event", "bodyhash", "processing", 2, False)])

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == PAYLOAD_CONFLICT
    assert result.attempt_count == 2


def test_claim_detects_payload_conflict_on_body_mismatch() -> None:
    repo, _cursor, _runtime = _repo([("handoff.requested", "different", "processing", 3, False)])

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == PAYLOAD_CONFLICT
    assert result.attempt_count == 3


def test_claim_returns_duplicate_when_already_delivered() -> None:
    repo, _cursor, _runtime = _repo([("handoff.requested", "bodyhash", "delivered", 1, False)])

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == DUPLICATE
    assert result.attempt_count == 1


def test_claim_returns_in_progress_for_fresh_processing_row() -> None:
    # status processing and NOT stale -> another worker holds it.
    repo, _cursor, _runtime = _repo([("handoff.requested", "bodyhash", "processing", 4, False)])

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == IN_PROGRESS
    assert result.attempt_count == 4


def test_claim_reclaims_stale_processing_row() -> None:
    # processing but stale -> UPDATE bumps attempt_count and re-claims.
    repo, cursor, _runtime = _repo(
        [("handoff.requested", "bodyhash", "processing", 4, True), (5,)]
    )

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == CLAIMED
    assert result.attempt_count == 5
    assert "UPDATE webhook_ingress_receipts" in cursor.executed[1][0]


def test_claim_reclaims_retryable_failed_row() -> None:
    # any non-delivered, non-fresh-processing status re-claims via UPDATE.
    repo, _cursor, _runtime = _repo(
        [("handoff.requested", "bodyhash", "retryable_failed", 1, False), (2,)]
    )

    result = repo.claim(
        event_type="handoff.requested",
        idempotency_key="k",
        request_id="r",
        body_hash="bodyhash",
    )

    assert result.status == CLAIMED
    assert result.attempt_count == 2


def test_mark_delivered_sets_delivered_status_and_timestamp() -> None:
    repo, cursor, runtime = _repo([])

    repo.mark_delivered("handoff:req-1")

    assert runtime.transactions == 1
    sql, params = cursor.executed[0]
    assert "SET status = %s" in sql
    assert params[0] == "delivered"
    assert params[1] is None  # last_error_code cleared
    assert params[2] == "delivered"  # delivered_at CASE guard
    assert params[3] == idempotency_hash("handoff:req-1")


def test_mark_failed_records_error_code_without_clearing_delivery() -> None:
    repo, cursor, _runtime = _repo([])

    repo.mark_failed("handoff:req-1", "verified_webhook_delivery_failed")

    _sql, params = cursor.executed[0]
    assert params[0] == "retryable_failed"
    assert params[1] == "verified_webhook_delivery_failed"


def test_verify_signature_rejects_non_numeric_timestamp() -> None:
    assert not verify_signature(
        body=b"{}",
        timestamp="not-a-number",
        signature="sha256=abc",
        secret="s",
    )


def test_verify_signature_rejects_missing_inputs() -> None:
    assert not verify_signature(body=b"{}", timestamp=None, signature="sha256=x", secret="s")
    assert not verify_signature(body=b"{}", timestamp="1", signature=None, secret="s")
    assert not verify_signature(body=b"{}", timestamp="1", signature="sha256=x", secret="")
    # signature without the required prefix is rejected.
    assert not verify_signature(body=b"{}", timestamp="1", signature="abc", secret="s")


def test_payload_hash_is_stable_sha256() -> None:
    import hashlib

    body = b'{"summary":"safe"}'
    assert payload_hash(body) == hashlib.sha256(body).hexdigest()
