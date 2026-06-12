from contextlib import contextmanager

import pytest

from scripts.prune_operational_data import prune_batch, prune_operational_data


class RecordingCursor:
    def __init__(
        self,
        counts: list[int] | None = None,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.counts = iter(counts or [])
        self.rowcounts = iter(rowcounts or [])
        self.calls: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple) -> None:
        self.calls.append((sql, params))
        self.rowcount = next(self.rowcounts, 1)

    def fetchone(self):
        return (next(self.counts),)


class RecordingConnection:
    def __init__(self, cursors: list[RecordingCursor]) -> None:
        self.cursors = iter(cursors)
        self.transaction_count = 0
        self.used_cursors: list[RecordingCursor] = []

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield

    @contextmanager
    def cursor(self):
        cursor = next(self.cursors)
        self.used_cursors.append(cursor)
        yield cursor


def test_prune_dry_run_counts_all_safe_targets_without_delete() -> None:
    cursor = RecordingCursor([1, 2, 3, 4, 5, 6, 7])

    counts = prune_batch(
        cursor,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=100,
        dry_run=True,
    )

    rendered = " ".join(sql for sql, _ in cursor.calls).lower()
    assert counts == {
        "messages": 1,
        "conversations": 2,
        "feedback": 3,
        "chat_audits": 4,
        "otp_challenges": 5,
        "operational_outbox_delivered": 6,
        "webhook_ingress_receipts_delivered": 7,
    }
    assert "delete from" not in rendered
    assert "status = 'delivered'" in rendered
    assert "processed_at is not null" in rendered
    assert "delivered_at is not null" in rendered


def test_prune_deletes_in_dependency_safe_order_and_only_delivered_external_rows() -> None:
    cursor = RecordingCursor()

    counts = prune_batch(
        cursor,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=100,
        dry_run=False,
    )

    rendered = " ".join(sql for sql, _ in cursor.calls).lower()
    outbox_sql = cursor.calls[-2][0].lower()
    receipt_sql = cursor.calls[-1][0].lower()
    audit_sql = cursor.calls[3][0].lower()
    assert list(counts) == [
        "messages",
        "conversations",
        "feedback",
        "chat_audits",
        "otp_challenges",
        "operational_outbox_delivered",
        "webhook_ingress_receipts_delivered",
    ]
    assert "for update skip locked" in rendered
    assert "not exists" in audit_sql
    assert "from feedback" in audit_sql
    assert "feedback.chat_audit_id = chat_audits.id" in audit_sql
    for external_sql in (outbox_sql, receipt_sql):
        assert "status = 'delivered'" in external_sql
        assert "status = 'pending'" not in external_sql
        assert "status = 'dead_letter'" not in external_sql
        assert "status = 'retryable_failed'" not in external_sql


def test_prune_orders_expired_feedback_before_unreferenced_chat_audits() -> None:
    cursor = RecordingCursor()

    prune_batch(
        cursor,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=100,
        dry_run=False,
    )

    feedback_sql = cursor.calls[2][0].lower()
    audit_sql = cursor.calls[3][0].lower()
    assert "delete from feedback" in feedback_sql
    assert "delete from chat_audits" in audit_sql
    assert "where feedback.chat_audit_id = chat_audits.id" in audit_sql


def test_pruning_processes_multiple_transactional_batches_until_drained() -> None:
    first = RecordingCursor(rowcounts=[2, 2, 2, 2, 2, 2, 2])
    second = RecordingCursor(rowcounts=[1, 1, 1, 1, 1, 1, 1])
    connection = RecordingConnection([first, second])

    result = prune_operational_data(
        connection,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=2,
        max_batches=5,
        dry_run=False,
    )

    assert result.batches_run == 2
    assert result.limit_reached is False
    assert connection.transaction_count == 2
    assert all(count == 3 for count in result.counts.values())


def test_pruning_stops_at_max_batches_and_reports_possible_remaining_rows() -> None:
    connection = RecordingConnection(
        [
            RecordingCursor(rowcounts=[2, 2, 2, 2, 2, 2, 2]),
            RecordingCursor(rowcounts=[2, 2, 2, 2, 2, 2, 2]),
        ]
    )

    result = prune_operational_data(
        connection,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=2,
        max_batches=2,
        dry_run=False,
    )

    assert result.batches_run == 2
    assert result.limit_reached is True
    assert connection.transaction_count == 2
    assert all(count == 4 for count in result.counts.values())


def test_pruning_dry_run_scans_bounded_capacity_without_mutation() -> None:
    cursor = RecordingCursor(counts=[6, 5, 4, 3, 2, 1, 0])
    connection = RecordingConnection([cursor])

    result = prune_operational_data(
        connection,
        conversation_days=60,
        otp_days=7,
        outbox_delivered_days=30,
        receipt_days=30,
        batch_size=2,
        max_batches=3,
        dry_run=True,
    )

    rendered = " ".join(sql for sql, _ in cursor.calls).lower()
    assert result.batches_run == 0
    assert result.limit_reached is True
    assert result.counts["messages"] == 6
    assert all(params[-1] == 6 for _, params in cursor.calls)
    assert "delete from" not in rendered


def test_pruning_rejects_a_run_above_the_per_target_safety_limit() -> None:
    connection = RecordingConnection([])

    with pytest.raises(ValueError, match="per-target safety limit"):
        prune_operational_data(
            connection,
            conversation_days=60,
            otp_days=7,
            outbox_delivered_days=30,
            receipt_days=30,
            batch_size=5000,
            max_batches=50,
            dry_run=False,
        )

    assert connection.transaction_count == 0
