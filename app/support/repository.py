"""Read-only PostgreSQL adapter for the support case inbox.

The case row is durable (migration 009); the rich context is assembled
on-read by following ``support_cases.conversation_id`` into the already
sanitized ``messages`` transcript. Nothing here writes or re-sanitizes.
"""

from __future__ import annotations

import dataclasses
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
    # Fase B: dono do caso e tempo pausado real (dos eventos), so preenchidos
    # pelos metodos do console (list_active_cases/list_history_cases).
    assignee_staff_id: str | None = None
    assignee_display_name: str | None = None
    waiting_seconds: float = 0.0


@dataclass(frozen=True)
class CaseEventSummary:
    action: str
    from_status: str
    to_status: str
    note: str | None
    actor_display_name: str
    created_at: Any


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
        assignee_staff_id: str | None = None,
    ) -> ActiveCaseSet:
        """Fetch the console's active set with the database clock attached.

        SQL only filters and limits (the operational queue is small by
        nature); attention ordering, SLA and color filtering happen in Python
        over this set. ``pending_consent`` only appears with an explicit
        status filter, same as the inbox. ``assignee_staff_id`` is the
        ``assignee=me`` filter (Fase B); ``None`` means unfiltered.
        """

        bounded_cap = max(1, int(cap))
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sc.id, d.name, sc.status, sc.priority, sc.channel,
                           sc.request_id, sc.reason_codes,
                           sc.context_snapshot_sanitized, sc.opened_at,
                           sc.updated_at, sc.assignee_staff_id, am.display_name,
                           now() AS db_now
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    LEFT JOIN staff_members am ON am.id = sc.assignee_staff_id
                    WHERE sc.status NOT IN ('closed', 'cancelled')
                      AND (%s::text IS NULL OR d.name = %s)
                      AND (
                        (%s::text IS NULL AND sc.status != 'pending_consent')
                        OR sc.status = %s
                      )
                      AND (%s::uuid IS NULL OR sc.assignee_staff_id = %s)
                    ORDER BY sc.opened_at ASC
                    LIMIT %s
                    """,
                    (
                        domain,
                        domain,
                        status,
                        status,
                        assignee_staff_id,
                        assignee_staff_id,
                        bounded_cap + 1,
                    ),
                )
                rows = cursor.fetchall()
                truncated = len(rows) > bounded_cap
                rows = rows[:bounded_cap]
                db_now = rows[0][12] if rows else None
                waiting_by_case = (
                    self._load_waiting_seconds(
                        cursor, [str(row[0]) for row in rows], db_now
                    )
                    if rows
                    else {}
                )
        return ActiveCaseSet(
            cases=[
                self._to_console_summary(
                    row, waiting_seconds=waiting_by_case.get(str(row[0]), 0.0)
                )
                for row in rows
            ],
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
        assignee_staff_id: str | None = None,
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
                           sc.updated_at, sc.assignee_staff_id, am.display_name
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    LEFT JOIN staff_members am ON am.id = sc.assignee_staff_id
                    WHERE sc.status IN ('closed', 'cancelled')
                      AND (%s::text IS NULL OR d.name = %s)
                      AND (%s::text IS NULL OR sc.status = %s)
                      AND (%s::uuid IS NULL OR sc.assignee_staff_id = %s)
                    ORDER BY sc.opened_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (
                        domain,
                        domain,
                        status,
                        status,
                        assignee_staff_id,
                        assignee_staff_id,
                        bounded_limit,
                        bounded_offset,
                    ),
                )
                rows = cursor.fetchall()
        return [self._to_console_summary(row) for row in rows]

    def database_now(self) -> Any:
        """Database clock, so SLA math never mixes clocks with ``opened_at``."""

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT now()")
                return cursor.fetchone()[0]

    def get_case_waiting_seconds(self, case_id: str, db_now: Any) -> float:
        """Total paused time for a single case (detail view SLA math)."""

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                waiting = self._load_waiting_seconds(cursor, [case_id], db_now)
        return waiting.get(str(case_id), 0.0)

    def get_case_events(self, case_id: str) -> list[CaseEventSummary]:
        """Audit trail of transitions (Fase B), oldest first."""

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.action, e.from_status, e.to_status,
                           e.note_sanitized, m.display_name, e.created_at
                    FROM support_case_events e
                    JOIN staff_members m ON m.id = e.actor_staff_id
                    WHERE e.case_id = %s
                    ORDER BY e.created_at ASC
                    """,
                    (case_id,),
                )
                rows = cursor.fetchall()
        return [
            CaseEventSummary(
                action=str(row[0]),
                from_status=str(row[1]),
                to_status=str(row[2]),
                note=row[3],
                actor_display_name=str(row[4]),
                created_at=row[5],
            )
            for row in rows
        ]

    def _load_waiting_seconds(
        self,
        cursor: Any,
        case_ids: list[str],
        db_now: Any,
    ) -> dict[str, float]:
        """Sum ``wait_customer`` -> ``resume`` intervals per case.

        A pause still open (no matching ``resume`` event yet) counts through
        ``db_now`` -- the relogio pausa de verdade enquanto o caso segue
        ``waiting_customer``.
        """

        if not case_ids:
            return {}
        cursor.execute(
            """
            SELECT case_id, action, created_at
            FROM support_case_events
            WHERE case_id = ANY(%s) AND action IN ('wait_customer', 'resume')
            ORDER BY case_id, created_at ASC
            """,
            (case_ids,),
        )
        waiting: dict[str, float] = {}
        open_pause_started_at: dict[str, Any] = {}
        for case_id, action, created_at in cursor.fetchall():
            key = str(case_id)
            if action == "wait_customer":
                open_pause_started_at[key] = created_at
            elif action == "resume":
                started_at = open_pause_started_at.pop(key, None)
                if started_at is not None:
                    waiting[key] = waiting.get(key, 0.0) + (
                        created_at - started_at
                    ).total_seconds()
        for key, started_at in open_pause_started_at.items():
            if db_now is not None:
                waiting[key] = waiting.get(key, 0.0) + (db_now - started_at).total_seconds()
        return waiting

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
                            LIMIT 1),
                           sc.assignee_staff_id, am.display_name
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    LEFT JOIN customers c ON c.id = sc.customer_id
                    LEFT JOIN staff_members am ON am.id = sc.assignee_staff_id
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
            "assignee_staff_id": case_row[14],
            "assignee_display_name": case_row[15],
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

    def _to_console_summary(
        self, row: tuple, *, waiting_seconds: float = 0.0
    ) -> SupportCaseSummary:
        """Console rows append ``assignee_staff_id, display_name`` (and,
        for the active set, ``db_now``) after the legacy 10-column shape."""

        base = self._to_summary(row[:10])
        assignee_staff_id, assignee_display_name = row[10], row[11]
        return dataclasses.replace(
            base,
            assignee_staff_id=str(assignee_staff_id) if assignee_staff_id else None,
            assignee_display_name=(
                str(assignee_display_name) if assignee_display_name else None
            ),
            waiting_seconds=waiting_seconds,
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
