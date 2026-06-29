"""Read-only PostgreSQL adapter for the support case inbox.

The case row is durable (migration 009); the rich context is assembled
on-read by following ``support_cases.conversation_id`` into the already
sanitized ``messages`` transcript. Nothing here writes or re-sanitizes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db.runtime import DatabaseRuntime
from app.support.context import SupportCaseContext, build_case_context
from app.support.transcript import fetch_conversation_transcript


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_TRANSCRIPT_TURNS = 200


@dataclass(frozen=True)
class SupportCaseSummary:
    case_id: str
    domain: str
    status: str
    priority: str
    channel: str
    request_id: str
    reason_codes: list[str]
    summary: str | None
    turn_count: int | None
    opened_at: Any
    updated_at: Any


class SupportCaseRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def list_cases(
        self,
        *,
        domain: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[SupportCaseSummary]:
        bounded_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        bounded_offset = max(0, int(offset))
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sc.id, d.name, sc.status, sc.priority, sc.channel,
                           sc.request_id, sc.reason_codes,
                           sc.context_snapshot_sanitized, sc.opened_at,
                           sc.updated_at
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE (%s::text IS NULL OR d.name = %s)
                      AND (%s::text IS NULL OR sc.status = %s)
                    ORDER BY sc.opened_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (
                        domain,
                        domain,
                        status,
                        status,
                        bounded_limit,
                        bounded_offset,
                    ),
                )
                rows = cursor.fetchall()
        return [self._to_summary(row) for row in rows]

    def get_case_with_context(self, case_id: str) -> SupportCaseContext | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sc.id, d.name, sc.status, sc.priority, sc.channel,
                           sc.request_id, sc.reason_codes,
                           sc.context_snapshot_sanitized, sc.conversation_id,
                           sc.opened_at, sc.updated_at
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE sc.id = %s
                    """,
                    (case_id,),
                )
                case_row = cursor.fetchone()
                if case_row is None:
                    return None
                conversation_id = case_row[8]
                transcript_rows = self._load_transcript(cursor, conversation_id)
        case = {
            "id": case_row[0],
            "domain": case_row[1],
            "status": case_row[2],
            "priority": case_row[3],
            "channel": case_row[4],
            "request_id": case_row[5],
            "reason_codes": _load_json(case_row[6], default=[]),
            "context_snapshot": _load_json(case_row[7], default={}),
            "opened_at": case_row[9],
            "updated_at": case_row[10],
        }
        return build_case_context(case, transcript_rows)

    def _load_transcript(
        self,
        cursor: Any,
        conversation_id: Any,
    ) -> list[dict[str, Any]]:
        return fetch_conversation_transcript(
            cursor, conversation_id, limit=MAX_TRANSCRIPT_TURNS
        )

    def _to_summary(self, row: tuple) -> SupportCaseSummary:
        snapshot = _load_json(row[7], default={})
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        summary = snapshot.get("summary")
        organized = snapshot.get("organized_context")
        turn_count = None
        if isinstance(organized, dict) and isinstance(
            organized.get("turn_count"), int
        ):
            turn_count = organized["turn_count"]
        return SupportCaseSummary(
            case_id=str(row[0]),
            domain=str(row[1]),
            status=str(row[2]),
            priority=str(row[3]),
            channel=str(row[4]),
            request_id=str(row[5]),
            reason_codes=_load_json(row[6], default=[]),
            summary=str(summary) if summary is not None else None,
            turn_count=turn_count,
            opened_at=row[8],
            updated_at=row[9],
        )


def _load_json(value: Any, *, default: Any) -> Any:
    """JSONB columns may arrive parsed (psycopg default) or as text."""

    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default
