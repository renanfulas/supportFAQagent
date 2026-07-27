"""Fase C: agregacoes de metricas do console (backlog, throughput, motivos de
escalonamento, feedback e tempos de resposta).

Uma fonte de verdade so: o backlog reusa o mesmo caminho Python da fila
(``compute_sla`` sobre o conjunto ativo devolvido por
``SupportCaseRepository.list_active_cases``) em vez de recalcular cor em SQL.
As demais agregacoes operam sobre janelas de 14/30 dias que nao cabem inteiras
em memoria como a fila operacional cabe, entao ficam em SQL dedicado
(``SupportMetricsRepository``).

Cortes diarios de ``throughput`` usam o fuso ``SUPPORT_CONSOLE_TIMEZONE``: um
corte em UTC deslocaria o fim de tarde do time para o dia seguinte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.db.runtime import DatabaseRuntime
from app.support.repository import SupportCaseRepository
from app.support.sla import compute_sla


WINDOW_DAYS = {"14d": 14, "30d": 30}
DEFAULT_WINDOW = "14d"
# Abaixo deste volume, o helpful_rate fica marcado como amostra pequena --
# staff nao deve tirar conclusao de 2 votos.
SAMPLE_SIZE_WARNING_THRESHOLD = 20
KNOWLEDGE_GAP_DEFAULT_LIMIT = 20
KNOWLEDGE_GAP_MAX_LIMIT = 100


@dataclass(frozen=True)
class MetricsWindow:
    start_utc: datetime
    end_utc: datetime
    start_date_local: date
    end_date_local: date


def resolve_window(window: str, *, now: datetime, timezone_name: str) -> MetricsWindow:
    """Janela de N dias corridos terminando hoje, no fuso do time.

    ``start_utc``/``end_utc`` filtram o SQL; ``start_date_local``/
    ``end_date_local`` guiam o zero-fill do throughput.
    """

    days = WINDOW_DAYS.get(window)
    if days is None:
        raise ValueError(f"unknown window: {window}")
    team_zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(team_zone)
    end_date_local = local_now.date()
    start_date_local = end_date_local - timedelta(days=days - 1)
    start_utc = datetime.combine(
        start_date_local, datetime.min.time(), tzinfo=team_zone
    ).astimezone(UTC)
    return MetricsWindow(
        start_utc=start_utc,
        end_utc=now,
        start_date_local=start_date_local,
        end_date_local=end_date_local,
    )


def build_backlog_metrics(
    repository: SupportCaseRepository,
    *,
    domain: str | None,
    cap: int,
    settings: Any,
) -> dict[str, Any]:
    active = repository.list_active_cases(domain=domain, status=None, cap=cap)
    by_color = {"green": 0, "yellow": 0, "red": 0, "paused": 0}
    by_status: dict[str, int] = {}
    for case in active.cases:
        sla = compute_sla(
            case.priority,
            case.opened_at,
            case.status,
            active.db_now,
            settings,
            waiting_seconds=case.waiting_seconds,
        )
        bucket = "paused" if sla.paused else sla.color
        by_color[bucket] = by_color.get(bucket, 0) + 1
        by_status[case.status] = by_status.get(case.status, 0) + 1
    return {"by_color": by_color, "by_status": by_status, "truncated": active.truncated}


def build_throughput_series(
    counts_by_day: dict[date, dict[str, int]],
    *,
    start_date_local: date,
    end_date_local: date,
) -> list[dict[str, Any]]:
    """Zero-fill todo dia da janela, mesmo sem atividade -- serie continua
    para o grafico nao ter buracos."""

    series: list[dict[str, Any]] = []
    current = start_date_local
    while current <= end_date_local:
        counts = counts_by_day.get(current, {})
        series.append(
            {
                "day": current.isoformat(),
                "opened": counts.get("opened", 0),
                "closed": counts.get("closed", 0),
            }
        )
        current += timedelta(days=1)
    return series


def build_feedback_block(raw: dict[str, int]) -> dict[str, Any]:
    helpful = int(raw.get("helpful", 0))
    not_helpful = int(raw.get("not_helpful", 0))
    total = helpful + not_helpful
    block: dict[str, Any] = {
        "helpful": helpful,
        "not_helpful": not_helpful,
        "helpful_rate": round(helpful / total, 4) if total else None,
        "unknown_domain_count": int(raw.get("unknown_domain_count", 0)),
    }
    if total < SAMPLE_SIZE_WARNING_THRESHOLD:
        block["sample_note"] = "amostra pequena"
    return block


class SupportMetricsRepository:
    """SQL agregado do console: janelas de 14/30 dias, uma consulta por bloco."""

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def get_throughput_counts(
        self,
        *,
        domain: str | None,
        window_start: datetime,
        window_end: datetime,
        timezone_name: str,
    ) -> dict[date, dict[str, int]]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT (sc.opened_at AT TIME ZONE %s)::date AS day, count(*)
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE sc.opened_at >= %s AND sc.opened_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    GROUP BY day
                    """,
                    (timezone_name, window_start, window_end, domain, domain),
                )
                opened_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT (sc.closed_at AT TIME ZONE %s)::date AS day, count(*)
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE sc.status IN ('closed', 'cancelled')
                      AND sc.closed_at >= %s AND sc.closed_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    GROUP BY day
                    """,
                    (timezone_name, window_start, window_end, domain, domain),
                )
                closed_rows = cursor.fetchall()
        counts: dict[date, dict[str, int]] = {}
        for day, count in opened_rows:
            counts.setdefault(day, {})["opened"] = int(count)
        for day, count in closed_rows:
            counts.setdefault(day, {})["closed"] = int(count)
        return counts

    def get_escalation_reasons(
        self,
        *,
        domain: str | None,
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict[str, Any]]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT reason_code, count(*)
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    CROSS JOIN LATERAL jsonb_array_elements_text(sc.reason_codes)
                      AS reason_code
                    WHERE sc.opened_at >= %s AND sc.opened_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    GROUP BY reason_code
                    ORDER BY count(*) DESC, reason_code ASC
                    """,
                    (window_start, window_end, domain, domain),
                )
                rows = cursor.fetchall()
        return [{"reason_code": str(row[0]), "count": int(row[1])} for row in rows]

    def get_feedback_metrics(
        self,
        *,
        domain: str | None,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, int]:
        # Orphan (chat_audit_id NULL) so entra quando domain nao filtra --
        # filtrar por dominio exclui naturalmente o que nao tem dominio
        # conhecido.
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      count(*) FILTER (WHERE f.helpful = true),
                      count(*) FILTER (WHERE f.helpful = false),
                      count(*) FILTER (WHERE f.chat_audit_id IS NULL)
                    FROM feedback f
                    LEFT JOIN chat_audits ca ON ca.id = f.chat_audit_id
                    LEFT JOIN domains d ON d.id = ca.domain_id
                    WHERE f.created_at >= %s AND f.created_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    """,
                    (window_start, window_end, domain, domain),
                )
                helpful, not_helpful, unknown_domain_count = cursor.fetchone()
        return {
            "helpful": int(helpful or 0),
            "not_helpful": int(not_helpful or 0),
            "unknown_domain_count": int(unknown_domain_count or 0),
        }

    def get_response_times(
        self,
        *,
        domain: str | None,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, float | None]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT percentile_cont(0.5) WITHIN GROUP (
                      ORDER BY EXTRACT(EPOCH FROM (fa.first_action_at - sc.opened_at))
                    )
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    JOIN LATERAL (
                      SELECT min(created_at) AS first_action_at
                      FROM support_case_events e
                      WHERE e.case_id = sc.id
                    ) fa ON fa.first_action_at IS NOT NULL
                    WHERE sc.opened_at >= %s AND sc.opened_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    """,
                    (window_start, window_end, domain, domain),
                )
                median_first_action = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT percentile_cont(0.5) WITHIN GROUP (
                      ORDER BY EXTRACT(EPOCH FROM (sc.closed_at - sc.opened_at))
                    )
                    FROM support_cases sc
                    JOIN domains d ON d.id = sc.domain_id
                    WHERE sc.status IN ('closed', 'cancelled')
                      AND sc.closed_at >= %s AND sc.closed_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    """,
                    (window_start, window_end, domain, domain),
                )
                median_to_close = cursor.fetchone()[0]
        return {
            "median_seconds_to_first_action": (
                float(median_first_action) if median_first_action is not None else None
            ),
            "median_seconds_to_close": (
                float(median_to_close) if median_to_close is not None else None
            ),
        }

    def get_knowledge_gap_candidates(
        self,
        *,
        domain: str | None,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Perguntas com feedback negativo, sem referencia de conhecimento
        usada primeiro -- sinal direto para a fila de melhoria da base
        (docs/architecture/knowledge-authoring.md). ``question``/``comment``
        reusam o mesmo texto ja sanitizado que o transcript do inbox exibe;
        nao expoe nada novo em termos de privacidade."""
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                      ca.request_id,
                      d.name,
                      ca.question_sanitized,
                      f.reason,
                      f.comment_sanitized,
                      (jsonb_array_length(ca.message_references) = 0) AS has_no_reference,
                      f.created_at
                    FROM feedback f
                    JOIN chat_audits ca ON ca.id = f.chat_audit_id
                    JOIN domains d ON d.id = ca.domain_id
                    WHERE f.helpful = false
                      AND f.created_at >= %s AND f.created_at < %s
                      AND (%s::text IS NULL OR d.name = %s)
                    ORDER BY has_no_reference DESC, f.created_at DESC
                    LIMIT %s
                    """,
                    (window_start, window_end, domain, domain, limit),
                )
                rows = cursor.fetchall()
        return [
            {
                "request_id": str(row[0]),
                "domain": str(row[1]),
                "question": str(row[2]),
                "reason": row[3],
                "comment": row[4],
                "has_reference": not bool(row[5]),
                "created_at": (
                    row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6])
                ),
            }
            for row in rows
        ]


def build_console_metrics(
    *,
    case_repository: SupportCaseRepository,
    metrics_repository: SupportMetricsRepository,
    window: str,
    domain: str | None,
    settings: Any,
    now: datetime,
) -> dict[str, Any]:
    if window not in WINDOW_DAYS:
        raise ValueError(f"unknown window: {window}")
    bounds = resolve_window(
        window, now=now, timezone_name=settings.support_console_timezone
    )
    backlog = build_backlog_metrics(
        case_repository,
        domain=domain,
        cap=settings.support_console_active_cases_cap,
        settings=settings,
    )
    throughput_counts = metrics_repository.get_throughput_counts(
        domain=domain,
        window_start=bounds.start_utc,
        window_end=bounds.end_utc,
        timezone_name=settings.support_console_timezone,
    )
    throughput = build_throughput_series(
        throughput_counts,
        start_date_local=bounds.start_date_local,
        end_date_local=bounds.end_date_local,
    )
    escalation_reasons = metrics_repository.get_escalation_reasons(
        domain=domain, window_start=bounds.start_utc, window_end=bounds.end_utc
    )
    feedback = build_feedback_block(
        metrics_repository.get_feedback_metrics(
            domain=domain, window_start=bounds.start_utc, window_end=bounds.end_utc
        )
    )
    response_times = metrics_repository.get_response_times(
        domain=domain, window_start=bounds.start_utc, window_end=bounds.end_utc
    )
    return {
        "backlog": backlog,
        "throughput": throughput,
        "escalation_reasons": escalation_reasons,
        "feedback": feedback,
        "response_times": response_times,
    }


def build_knowledge_gap_report(
    *,
    metrics_repository: SupportMetricsRepository,
    window: str,
    domain: str | None,
    limit: int,
    settings: Any,
    now: datetime,
) -> dict[str, Any]:
    if window not in WINDOW_DAYS:
        raise ValueError(f"unknown window: {window}")
    bounds = resolve_window(
        window, now=now, timezone_name=settings.support_console_timezone
    )
    items = metrics_repository.get_knowledge_gap_candidates(
        domain=domain,
        window_start=bounds.start_utc,
        window_end=bounds.end_utc,
        limit=limit,
    )
    return {"items": items}
