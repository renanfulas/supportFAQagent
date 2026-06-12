from __future__ import annotations

import json
from typing import Any

from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime


ACTIVE_CONVERSATION_STATUSES = ("bot", "handoff_pending", "human_active")


class ConversationRepository:
    """PostgreSQL adapter that only accepts hashed and sanitized values."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def load_recent(
        self,
        *,
        domain: str,
        channel: str,
        session_hash: str,
        session_hash_version: str,
        limit: int,
    ) -> list[dict[str, str]]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.role, m.content
                    FROM conversations c
                    JOIN domains d ON d.id = c.domain_id
                    JOIN messages m ON m.conversation_id = c.id
                    WHERE d.name = %s
                      AND c.channel = %s
                      AND c.session_hash = %s
                      AND c.session_hash_version = %s
                      AND c.status IN ('bot', 'handoff_pending', 'human_active')
                      AND m.role IN ('user', 'assistant')
                      AND m.redaction_version = %s
                    ORDER BY m.message_sequence DESC
                    LIMIT %s
                    """,
                    (
                        domain,
                        channel,
                        session_hash,
                        session_hash_version,
                        REDACTION_VERSION,
                        limit,
                    ),
                )
                rows = cursor.fetchall()
        return [
            {"role": str(role), "content": str(content)}
            for role, content in reversed(rows)
        ]

    def append_turn(
        self,
        *,
        cursor: Any,
        domain_id: Any,
        session_hash: str,
        session_hash_version: str,
        channel: str,
        audit_id: Any,
        turn_id: str,
        request_id: str,
        question_sanitized: str,
        answer_sanitized: str,
        confidence: float,
        escalated: bool,
        handoff_reasons: list[str],
        references: list[str],
        error_code: str | None,
    ) -> None:
        sanitized_handoff_reasons = _sanitize_string_list(handoff_reasons)
        sanitized_references = _sanitize_string_list(references)
        sanitized_error_code = sanitize_for_persistence(error_code)
        cursor.execute(
            """
            INSERT INTO conversations (
              domain_id, channel, session_hash, session_hash_version,
              status, last_message_at
            )
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (domain_id, channel, session_hash)
              WHERE session_hash IS NOT NULL
                AND status IN ('bot', 'handoff_pending', 'human_active')
            DO UPDATE SET
              status = CASE
                WHEN conversations.status IN ('handoff_pending', 'human_active')
                  THEN conversations.status
                ELSE EXCLUDED.status
              END,
              session_hash_version = EXCLUDED.session_hash_version,
              updated_at = now(),
              last_message_at = now()
            RETURNING id
            """,
            (
                domain_id,
                channel,
                session_hash,
                session_hash_version,
                "handoff_pending" if escalated else "bot",
            ),
        )
        conversation_id = cursor.fetchone()[0]
        shared = (
            conversation_id,
            turn_id,
            request_id,
            channel,
            audit_id,
            json.dumps(sanitized_handoff_reasons),
            REDACTION_VERSION,
        )
        cursor.execute(
            """
            INSERT INTO messages (
              conversation_id, turn_id, request_id, channel, chat_audit_id,
              role, content, escalated, handoff_reasons, message_references,
              error_code, redaction_version
            )
            VALUES (%s, %s, %s, %s, %s, 'user', %s, false, %s::jsonb, '[]'::jsonb, NULL, %s)
            ON CONFLICT (conversation_id, turn_id, role) WHERE turn_id IS NOT NULL
            DO NOTHING
            """,
            (*shared[:5], question_sanitized, shared[5], shared[6]),
        )
        cursor.execute(
            """
            INSERT INTO messages (
              conversation_id, turn_id, request_id, channel, chat_audit_id,
              role, content, confidence, escalated, handoff_reasons,
              message_references, error_code, redaction_version
            )
            VALUES (%s, %s, %s, %s, %s, 'assistant', %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (conversation_id, turn_id, role) WHERE turn_id IS NOT NULL
            DO NOTHING
            """,
            (
                *shared[:5],
                answer_sanitized,
                confidence,
                escalated,
                shared[5],
                json.dumps(sanitized_references),
                sanitized_error_code,
                shared[6],
            ),
        )


def _sanitize_string_list(values: list[str]) -> list[str]:
    sanitized = sanitize_payload(values)
    if not isinstance(sanitized, list) or not all(
        isinstance(item, str) for item in sanitized
    ):
        raise TypeError("persisted metadata must be a list of strings")
    return sanitized
