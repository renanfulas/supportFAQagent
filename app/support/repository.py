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


@dataclass(frozen=True)
class ActiveCaseSet:
    """Conjunto ativo para o console: casos nao-fechados + relogio do banco.

    ``db_now`` sai da mesma query que ``opened_at`` (mesmo relogio, sem
    drift); todo o calculo de SLA/ordenacao acontece em Python sobre este
    conjunto. ``truncated`` marca quando o cap foi atingido.
    """

    cases: list[SupportCaseSummary]
    db_now: Any
    truncated: bool


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
                      AND (
                        (%s::text IS NULL AND sc.status != 'pending_consent')
                        OR sc.status = %s
                      )
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

    def list_active_cases(
        self,
        *,
        domain: str | None,
        status: str | None,
        cap: int,
    ) -> ActiveCaseSet:
        """Fetch the console's active set with the database clock attached.

        SQL only filters and limits (the operational queue is small by
        nature); attention ordering, SLA and color filtering happen in Python
        over this set. ``pending_consent`` only appears with an explicit
        status filter, same as the inbox.
        """

        bounded_cap = max(1, int(cap))
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sc.id, d.name, sc.status, sc.priority, sc.channel,
                           sc.request_id, sc.reason_codes,
                           sc.context_snapshot_sanitized, sc.opened_at,
                           sc.updated_at, now() AS db_now
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE sc.status NOT IN ('closed', 'cancelled')
                      AND (%s::text IS NULL OR d.name = %s)
                      AND (
                        (%s::text IS NULL AND sc.status != 'pending_consent')
                        OR sc.status = %s
                      )
                    ORDER BY sc.opened_at ASC
                    LIMIT %s
                    """,
                    (
                        domain,
                        domain,
                        status,
                        status,
                        bounded_cap + 1,
                    ),
                )
                rows = cursor.fetchall()
        truncated = len(rows) > bounded_cap
        rows = rows[:bounded_cap]
        db_now = rows[0][10] if rows else None
        return ActiveCaseSet(
            cases=[self._to_summary(row) for row in rows],
            db_now=db_now,
            truncated=truncated,
        )

    def list_history_cases(
        self,
        *,
        domain: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[SupportCaseSummary]:
        """Closed/cancelled cases; plain SQL pagination, no SLA math."""

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
                    WHERE sc.status IN ('closed', 'cancelled')
                      AND (%s::text IS NULL OR d.name = %s)
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

    def database_now(self) -> Any:
        """Database clock, so SLA math never mixes clocks with ``opened_at``."""

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT now()")
                return cursor.fetchone()[0]

    def get_case_with_context(self, case_id: str) -> SupportCaseContext | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                # LEFT JOIN customers: the contact block the customer authorized
                # via the LGPD consent path is read from its single source of
                # truth (`customers` + latest verified identity), so a replayed
                # turn overwriting the case snapshot can never lose it.
                cursor.execute(
                    """
                    SELECT sc.id, d.name, sc.status, sc.priority, sc.channel,
                           sc.request_id, sc.reason_codes,
                           sc.context_snapshot_sanitized, sc.conversation_id,
                           sc.opened_at, sc.updated_at,
                           c.display_label, c.email,
                           (SELECT vi.phone_last4
                            FROM verified_identities vi
                            WHERE vi.customer_id = c.id
                              AND vi.status = 'verified'
                            ORDER BY vi.verified_at DESC
                            LIMIT 1)
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    LEFT JOIN customers c ON c.id = sc.customer_id
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
            "customer_display_label": case_row[11],
            "customer_email": case_row[12],
            "customer_phone_last4": case_row[13],
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
