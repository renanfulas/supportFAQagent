"""Critical PostgreSQL structure required after the Phase 0 contract migration."""

from typing import Any


CONTRACT_MIGRATION = "009_customer_identity_support_cases.sql"

REQUIRED_COLUMNS = {
    "chat_audits": {
        "request_id",
        "session_hash",
        "session_hash_version",
        "request_fingerprint",
        "redaction_version",
    },
    "conversations": {
        "customer_id",
        "session_hash",
        "session_hash_version",
        "last_message_at",
    },
    "customer_preferences": {
        "id",
        "customer_id",
        "domain_id",
        "preferences_json",
        "version",
        "created_at",
        "updated_at",
    },
    "customers": {
        "id",
        "status",
        "default_channel",
        "last_seen_at",
        "created_at",
        "updated_at",
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
    "support_cases": {
        "id",
        "domain_id",
        "customer_id",
        "conversation_id",
        "request_id",
        "channel",
        "status",
        "priority",
        "reason_codes",
        "context_snapshot_sanitized",
        "idempotency_key",
        "assigned_team",
        "opened_at",
        "updated_at",
        "closed_at",
    },
    "verified_identities": {
        "customer_id",
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
    "idx_conversations_customer",
    "idx_customer_preferences_customer_domain",
    "idx_customer_preferences_customer_global",
    "idx_customer_preferences_domain",
    "idx_customers_last_seen",
    "idx_customers_status",
    "idx_feedback_idempotency_key",
    "idx_messages_turn_role",
    "idx_outbox_dispatch",
    "idx_support_cases_domain_status_opened",
    "idx_support_cases_customer",
    "idx_support_cases_conversation",
    "idx_support_cases_request",
    "idx_verified_identities_customer",
    "idx_webhook_ingress_status_updated",
}

REQUIRED_TRIGGERS = {
    "chat_audits_legacy_hash_version",
    "feedback_legacy_hash_version",
}

FORBIDDEN_TRIGGERS = {"conversations_legacy_writer_guard"}

REQUIRED_CONSTRAINTS = {
    "chat_audits_session_hash_version_check",
    "customer_preferences_json_object_check",
    "customer_preferences_version_check",
    "customers_status_check",
    "feedback_idempotency_fingerprint_check",
    "feedback_session_hash_version_check",
    "otp_challenges_status_check",
    "support_cases_context_snapshot_object_check",
    "support_cases_closed_at_check",
    "support_cases_idempotency_key_unique",
    "support_cases_priority_check",
    "support_cases_reason_codes_array_check",
    "support_cases_status_check",
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
