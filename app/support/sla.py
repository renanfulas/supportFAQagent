"""Semaforo de SLA do console de suporte: uma unica fonte de verdade.

Todo o calculo acontece aqui, em Python puro, sobre o relogio do banco
(``db_now`` vem na mesma query que ``opened_at``, entao nao existe drift).
O SQL apenas filtra e limita; ordenacao "attention" e filtro por cor operam
sobre o conjunto ja calculado, o que garante consistencia com a cor exibida.

Fase A: casos pausados (aguardando cliente ou consentimento) nunca ficam
vermelhos e o ratio exibido e o tempo total (aproximacao declarada). Na Fase B
``waiting_seconds`` passa a vir dos eventos e o relogio pausa de verdade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


PRIORITY_WEIGHT = {"urgent": 4, "high": 3, "normal": 2, "low": 1}
PRIORITY_LABEL_PT_BR = {
    "urgent": "urgente",
    "high": "alta",
    "normal": "normal",
    "low": "baixa",
}
PAUSED_STATUSES = {"waiting_customer", "pending_consent"}
PAUSED_EXPLANATION = {
    "waiting_customer": "aguardando cliente",
    "pending_consent": "aguardando consentimento",
}

GREEN_BELOW = 0.6

SLA_COLORS = ("green", "yellow", "red")
COLOR_FILTERS = SLA_COLORS + ("paused",)


@dataclass(frozen=True)
class SlaAssessment:
    deadline_at: datetime
    elapsed_ratio: float
    color: str
    paused: bool
    explanation: str


def compute_sla(
    priority: str,
    opened_at: datetime,
    status: str,
    db_now: datetime,
    settings: Any,
    waiting_seconds: float = 0,
) -> SlaAssessment:
    """Assess a single case against its priority SLA.

    ``opened_at`` and ``db_now`` must come from the same clock (the database's,
    fetched in the same query). ``waiting_seconds`` is Fase B: total time spent
    paused, subtracted from the active elapsed time and pushed onto the
    deadline.
    """

    sla_minutes = _sla_minutes(priority, settings)
    sla_seconds = sla_minutes * 60
    waiting_seconds = max(0.0, float(waiting_seconds))
    deadline_at = opened_at + timedelta(minutes=sla_minutes, seconds=waiting_seconds)
    total_elapsed = (db_now - opened_at).total_seconds()
    active_elapsed = max(0.0, total_elapsed - waiting_seconds)
    elapsed_ratio = active_elapsed / sla_seconds
    paused = status in PAUSED_STATUSES

    if elapsed_ratio < GREEN_BELOW:
        color = "green"
    elif elapsed_ratio <= 1.0:
        color = "yellow"
    else:
        color = "red"
    if paused and color == "red":
        color = "yellow"

    return SlaAssessment(
        deadline_at=deadline_at,
        elapsed_ratio=round(elapsed_ratio, 4),
        color=color,
        paused=paused,
        explanation=_explanation(
            priority=priority,
            status=status,
            total_elapsed_seconds=total_elapsed,
            overdue_seconds=active_elapsed - sla_seconds,
            paused=paused,
        ),
    )


def attention_sort_key(
    *,
    priority: str,
    opened_at: datetime,
    sla: SlaAssessment,
) -> tuple:
    """Deterministic queue order: mesma entrada, mesma fila.

    Overdue-and-not-paused first, then priority weight, then oldest first.
    """

    overdue_active = sla.elapsed_ratio > 1.0 and not sla.paused
    return (
        0 if overdue_active else 1,
        -PRIORITY_WEIGHT.get(priority, PRIORITY_WEIGHT["normal"]),
        opened_at,
    )


def matches_color_filter(sla: SlaAssessment, color: str) -> bool:
    """``paused`` is its own bucket; the traffic-light colors exclude it."""

    if color == "paused":
        return sla.paused
    return sla.color == color and not sla.paused


def _sla_minutes(priority: str, settings: Any) -> int:
    by_priority = {
        "urgent": getattr(settings, "support_sla_minutes_urgent", 60),
        "high": getattr(settings, "support_sla_minutes_high", 120),
        "normal": getattr(settings, "support_sla_minutes_normal", 480),
        "low": getattr(settings, "support_sla_minutes_low", 1440),
    }
    return int(by_priority.get(priority, by_priority["normal"]))


def _explanation(
    *,
    priority: str,
    status: str,
    total_elapsed_seconds: float,
    overdue_seconds: float,
    paused: bool,
) -> str:
    """Staff-facing pt-BR completo (ortografia plena, como o resto do produto)."""

    label = PRIORITY_LABEL_PT_BR.get(priority, priority)
    opened = f"aberto há {_format_duration(total_elapsed_seconds)}"
    if paused:
        waiting = PAUSED_EXPLANATION.get(status, "aguardando cliente")
        return f"{label}, {opened}, {waiting}"
    if overdue_seconds > 0:
        return f"{label}, {opened}, prazo estourado há {_format_duration(overdue_seconds)}"
    return f"{label}, {opened}, prazo em {_format_duration(-overdue_seconds)}"


def _format_duration(seconds: float) -> str:
    total_minutes = int(max(0, seconds) // 60)
    if total_minutes < 1:
        return "menos de 1min"
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours > 0:
        return f"{hours}h{minutes:02d}" if minutes else f"{hours}h"
    return f"{total_minutes}min"
