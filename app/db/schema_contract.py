"""Critical PostgreSQL structure required after the Phase 0 contract migration."""

from typing import Any


CONTRACT_MIGRATION = "008_feedback_integrity.sql"

REQUIRED_COLUMNS = {
    "chat_audits": {
        "request_id",
        "session_hash",
        "session_hash_version",
        "request_fingerprint",
        "redaction_version",
    },
    "conversations": {
        "session_hash",
        "session_hash_version",
        "last_message_at",
    },
    "feedback": {
        "message_id",
        "session_hash_version",
        "idempotency_key",
        "feedback_fingerprint",
        "redaction_version",
    },
    "messages": {
        "turn_id",
        "request_id",
        "channel",
        "redaction_version",
        "chat_audit_id",
    },
    "operational_outbox": {
        "idempotency_key",
        "payload_sanitized",
        "status",
        "attempt_count",
        "available_at",
    },
    "webhook_ingress_receipts": {
        "idempotency_key_hash",
        "payload_hash",
        "status",
    },
}

FORBIDDEN_COLUMNS = {"conversations": {"session_id", "legacy_session_seen_at"}}

REQUIRED_INDEXES = {
    "idx_chat_audits_feedback_context",
    "idx_chat_audits_request_fingerprint",
    "idx_conversations_active_session",
    "idx_feedback_idempotency_key",
    "idx_messages_turn_role",
    "idx_outbox_dispatch",
    "idx_webhook_ingress_status_updated",
}

REQUIRED_TRIGGERS = {
    "chat_audits_legacy_hash_version",
    "feedback_legacy_hash_version",
}

FORBIDDEN_TRIGGERS = {"conversations_legacy_writer_guard"}

REQUIRED_CONSTRAINTS = {
    "chat_audits_session_hash_version_check",
    "feedback_idempotency_fingerprint_check",
    "feedback_session_hash_version_check",
    "otp_challenges_status_check",
}


def structural_drift(cursor: Any, schema: str) -> list[str]:
    """Return sanitized descriptions of missing or obsolete critical objects."""
    cursor.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        """,
        (schema, list(REQUIRED_COLUMNS | FORBIDDEN_COLUMNS)),
    )
    columns: dict[str, set[str]] = {}
    for table, column in cursor.fetchall():
        columns.setdefault(str(table), set()).add(str(column))

    errors = [
        f"missing column: {table}.{column}"
        for table, required in REQUIRED_COLUMNS.items()
        for column in sorted(required - columns.get(table, set()))
    ]
    errors.extend(
        f"obsolete column: {table}.{column}"
        for table, forbidden in FORBIDDEN_COLUMNS.items()
        for column in sorted(forbidden & columns.get(table, set()))
    )

    cursor.execute(
        "SELECT indexname FROM pg_catalog.pg_indexes WHERE schemaname = %s",
        (schema,),
    )
    indexes = {str(row[0]) for row in cursor.fetchall()}
    errors.extend(
        f"missing index: {name}" for name in sorted(REQUIRED_INDEXES - indexes)
    )

    cursor.execute(
        """
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE trigger_schema = %s
        """,
        (schema,),
    )
    triggers = {str(row[0]) for row in cursor.fetchall()}
    errors.extend(
        f"missing trigger: {name}" for name in sorted(REQUIRED_TRIGGERS - triggers)
    )
    errors.extend(
        f"obsolete trigger: {name}" for name in sorted(FORBIDDEN_TRIGGERS & triggers)
    )

    cursor.execute(
        """
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE constraint_schema = %s
        """,
        (schema,),
    )
    constraints = {str(row[0]) for row in cursor.fetchall()}
    errors.extend(
        f"missing constraint: {name}"
        for name in sorted(REQUIRED_CONSTRAINTS - constraints)
    )
    return errors
