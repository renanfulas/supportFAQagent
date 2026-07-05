"""Cursor-based transcript access shared by the read inbox and the handoff
write path. Keeping the SQL in one place is what lets read and push describe a
handoff from the same source: the sanitized ``messages`` rows of a conversation.
"""

from __future__ import annotations

from typing import Any

from app.core.persistence_sanitize import REDACTION_VERSION
from app.support.context import (
    SNAPSHOT_MAX_TURNS,
    build_snapshot_context,
)


READ_TRANSCRIPT_LIMIT = 200


TRANSCRIPT_ROLES = ("user", "assistant", "agent")


def fetch_conversation_transcript(
    cursor: Any,
    conversation_id: Any,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` turns, oldest first.

    Includes ``role='agent'`` (ponte WhatsApp<->console: the human agent's
    replies) alongside the bot's ``user``/``assistant`` turns, so the console
    case detail shows the full exchange. Deliberately NOT reused by
    ``ConversationHistoryService.load_recent`` (the bot's own RAG history
    replay), which stays user/assistant-only -- a live human handling the case
    should not feed back into the bot's prompt context.

    Ordering the inner query DESC then re-sorting ASC keeps the bound on the
    *recent* end of long conversations while still presenting turns in reading
    order. Works with any DB-API cursor (real or scripted in tests).
    """

    if conversation_id is None:
        return []
    cursor.execute(
        """
        SELECT sub.message_sequence, sub.role, sub.content, sub.confidence,
               sub.escalated, sub.handoff_reasons, sub.message_references,
               sub.error_code, sub.created_at
        FROM (
            SELECT m.message_sequence, m.role, m.content, m.confidence,
                   m.escalated, m.handoff_reasons, m.message_references,
                   m.error_code, m.created_at
            FROM messages m
            WHERE m.conversation_id = %s
              AND m.role = ANY(%s)
              AND m.redaction_version = %s
            ORDER BY m.message_sequence DESC
            LIMIT %s
        ) sub
        ORDER BY sub.message_sequence ASC
        """,
        (conversation_id, list(TRANSCRIPT_ROLES), REDACTION_VERSION, limit),
    )
    rows = cursor.fetchall()
    return [
        {
            "sequence": row[0],
            "role": row[1],
            "content": row[2],
            "confidence": row[3],
            "escalated": row[4],
            "handoff_reasons": row[5],
            "references": row[6],
            "error_code": row[7],
            "created_at": row[8],
        }
        for row in rows
    ]


def count_conversation_turns(cursor: Any, conversation_id: Any) -> int:
    if conversation_id is None:
        return 0
    cursor.execute(
        """
        SELECT count(*)
        FROM messages m
        WHERE m.conversation_id = %s
          AND m.role = ANY(%s)
          AND m.redaction_version = %s
        """,
        (conversation_id, list(TRANSCRIPT_ROLES), REDACTION_VERSION),
    )
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def build_support_snapshot_context(cursor: Any, conversation_id: Any) -> dict[str, Any]:
    """Assemble the bounded organized-context block stored on a support case.

    This is the push-side reuse of the read-side seam: it pulls the same
    sanitized turns, caps them for the outbox payload size budget, and reports
    the true total turn count so a consumer knows how much was elided.
    """

    if conversation_id is None:
        return build_snapshot_context([], total_turn_count=0)
    recent = fetch_conversation_transcript(
        cursor, conversation_id, limit=SNAPSHOT_MAX_TURNS
    )
    total = count_conversation_turns(cursor, conversation_id)
    return build_snapshot_context(recent, total_turn_count=total)
