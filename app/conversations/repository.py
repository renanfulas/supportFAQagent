from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime


ACTIVE_CONVERSATION_STATUSES = ("bot", "handoff_pending", "human_active")


@dataclass(frozen=True)
class PersistedConversationTurn:
    conversation_id: str


class ConversationRepository:
    """PostgreSQL adapter that only accepts hashed and sanitized values."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def load_recent(
        self,
        *,
        domain: str,
        channel: str,
        session_hash: str | None,
        session_hash_version: str,
        customer_id: str | None,
        limit: int,
    ) -> list[dict[str, str]]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                identity_filter, params = _history_identity_filter(
                    customer_id=customer_id,
                    session_hash=session_hash,
                    session_hash_version=session_hash_version,
                )
                status_filter = _history_status_filter(customer_id=customer_id)
                cursor.execute(
                    f"""
                    SELECT m.role, m.content
                    FROM conversations c
                    JOIN domains d ON d.id = c.domain_id
                    JOIN messages m ON m.conversation_id = c.id
                    WHERE d.name = %s
                      AND c.channel = %s
                      AND {identity_filter}
                      AND {status_filter}
                      AND m.role IN ('user', 'assistant')
                      AND m.redaction_version = %s
                    ORDER BY m.message_sequence DESC
                    LIMIT %s
                    """,
                    (
                        domain,
                        channel,
                        *params,
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
        customer_id: str | None = None,
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
        self._archive_identity_conflicts(
            cursor=cursor,
            domain_id=domain_id,
            channel=channel,
            session_hash=session_hash,
            customer_id=customer_id,
        )
        cursor.execute(
            """
            INSERT INTO conversations (
              domain_id, channel, session_hash, session_hash_version,
              customer_id, status, last_message_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (domain_id, channel, session_hash)
              WHERE session_hash IS NOT NULL
                AND status IN ('bot', 'handoff_pending', 'human_active')
            DO UPDATE SET
              status = CASE
                WHEN conversations.status IN ('handoff_pending', 'human_active')
                  THEN conversations.status
                ELSE EXCLUDED.status
              END,
              customer_id = COALESCE(conversations.customer_id, EXCLUDED.customer_id),
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
                customer_id,
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
        return PersistedConversationTurn(conversation_id=str(conversation_id))

    def _archive_identity_conflicts(
        self,
        *,
        cursor: Any,
        domain_id: Any,
        channel: str,
        session_hash: str,
        customer_id: str | None,
    ) -> PersistedConversationTurn:
        if customer_id:
            cursor.execute(
                """
                UPDATE conversations
                SET status = 'identity_changed', updated_at = now()
                WHERE domain_id = %s
                  AND channel = %s
                  AND session_hash = %s
                  AND customer_id IS NOT NULL
                  AND customer_id <> %s
                  AND status IN ('bot', 'handoff_pending', 'human_active')
                """,
                (domain_id, channel, session_hash, customer_id),
            )
            return

        cursor.execute(
            """
            UPDATE conversations
            SET status = 'identity_changed', updated_at = now()
            WHERE domain_id = %s
              AND channel = %s
              AND session_hash = %s
              AND customer_id IS NOT NULL
              AND status IN ('bot', 'handoff_pending', 'human_active')
            """,
            (domain_id, channel, session_hash),
        )


def _sanitize_string_list(values: list[str]) -> list[str]:
    sanitized = sanitize_payload(values)
    if not isinstance(sanitized, list) or not all(
        isinstance(item, str) for item in sanitized
    ):
        raise TypeError("persisted metadata must be a list of strings")
    return sanitized


def _history_identity_filter(
    *,
    customer_id: str | None,
    session_hash: str | None,
    session_hash_version: str,
) -> tuple[str, tuple[object, ...]]:
    if customer_id and session_hash:
        return (
            """
            (
                c.customer_id = %s
                OR (
                    c.customer_id IS NULL
                    AND c.session_hash = %s
                    AND c.session_hash_version = %s
                )
            )
            """,
            (customer_id, session_hash, session_hash_version),
        )
    if customer_id:
        return "c.customer_id = %s", (customer_id,)
    if session_hash:
        return (
            """
            c.customer_id IS NULL
            AND c.session_hash = %s
            AND c.session_hash_version = %s
            """,
            (session_hash, session_hash_version),
        )
    return "false", ()


def _history_status_filter(*, customer_id: str | None) -> str:
    if customer_id:
        return "c.status IN ('bot', 'handoff_pending', 'human_active', 'identity_changed')"
    return "c.status IN ('bot', 'handoff_pending', 'human_active')"
