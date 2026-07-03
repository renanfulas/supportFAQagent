"""Coverage for the console SLA math (pure functions, injected clock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.support.sla import (
    attention_sort_key,
    compute_sla,
    matches_color_filter,
)


SETTINGS = SimpleNamespace(
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
)

OPENED = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _sla(priority: str, *, minutes_elapsed: int, status: str = "open"):
    return compute_sla(
        priority,
        OPENED,
        status,
        OPENED + timedelta(minutes=minutes_elapsed),
        SETTINGS,
    )


# --------------------------------------------------------------------------- #
# Color thresholds: green < 0.6 <= yellow <= 1.0 < red
# --------------------------------------------------------------------------- #


def test_color_green_below_sixty_percent() -> None:
    sla = _sla("urgent", minutes_elapsed=35)
    assert sla.color == "green"
    assert not sla.paused
    assert sla.deadline_at == OPENED + timedelta(minutes=60)


def test_color_yellow_between_sixty_percent_and_deadline() -> None:
    assert _sla("urgent", minutes_elapsed=36).color == "yellow"
    assert _sla("urgent", minutes_elapsed=60).color == "yellow"


def test_color_red_after_deadline() -> None:
    sla = _sla("urgent", minutes_elapsed=61)
    assert sla.color == "red"
    assert sla.elapsed_ratio > 1.0


def test_unknown_priority_falls_back_to_normal_sla() -> None:
    sla = _sla("banana", minutes_elapsed=480)
    assert sla.deadline_at == OPENED + timedelta(minutes=480)


# --------------------------------------------------------------------------- #
# Paused cases never go red
# --------------------------------------------------------------------------- #


def test_paused_case_never_red_even_way_past_deadline() -> None:
    sla = _sla("urgent", minutes_elapsed=600, status="waiting_customer")
    assert sla.paused
    assert sla.color == "yellow"
    assert "aguardando cliente" in sla.explanation


def test_pending_consent_counts_as_paused() -> None:
    sla = _sla("normal", minutes_elapsed=10, status="pending_consent")
    assert sla.paused
    assert "aguardando consentimento" in sla.explanation


# --------------------------------------------------------------------------- #
# Explanations (staff-facing pt-BR, ortografia plena)
# --------------------------------------------------------------------------- #


def test_explanation_overdue_matches_plan_example() -> None:
    sla = _sla("urgent", minutes_elapsed=372)  # aberto ha 6h12, SLA 60min
    assert sla.explanation == "urgente, aberto há 6h12, prazo estourado há 5h12"


def test_explanation_within_deadline_shows_remaining_time() -> None:
    sla = _sla("high", minutes_elapsed=30)
    assert sla.explanation == "alta, aberto há 30min, prazo em 1h30"


def test_explanation_uses_days_for_long_waits() -> None:
    sla = _sla("low", minutes_elapsed=3 * 24 * 60)
    assert "aberto há 3d" in sla.explanation


# --------------------------------------------------------------------------- #
# Fase B seam: waiting_seconds pushes the deadline and pauses the clock
# --------------------------------------------------------------------------- #


def test_waiting_seconds_extends_deadline_and_discounts_elapsed() -> None:
    waited = 30 * 60
    sla = compute_sla(
        "urgent",
        OPENED,
        "open",
        OPENED + timedelta(minutes=60),
        SETTINGS,
        waiting_seconds=waited,
    )
    assert sla.deadline_at == OPENED + timedelta(minutes=90)
    assert sla.elapsed_ratio == 0.5
    assert sla.color == "green"


# --------------------------------------------------------------------------- #
# Attention ordering: overdue-active first, then priority, then oldest
# --------------------------------------------------------------------------- #


def test_attention_order_is_deterministic() -> None:
    now = OPENED + timedelta(hours=3)

    def entry(case_id: str, priority: str, opened_delta_minutes: int, status: str = "open"):
        opened = OPENED + timedelta(minutes=opened_delta_minutes)
        return case_id, priority, opened, compute_sla(priority, opened, status, now, SETTINGS)

    entries = [
        entry("normal-old", "normal", 0),
        entry("urgent-overdue", "urgent", 10),  # 2h50 > 60min SLA
        entry("urgent-paused-overdue", "urgent", 0, status="waiting_customer"),
        entry("high-fresh", "high", 170),
        entry("high-overdue", "high", 30),  # 2h30 > 2h SLA
    ]
    ordered = sorted(
        entries,
        key=lambda item: attention_sort_key(
            priority=item[1], opened_at=item[2], sla=item[3]
        ),
    )

    assert [item[0] for item in ordered] == [
        "urgent-overdue",
        "high-overdue",
        "urgent-paused-overdue",  # pausado nao fura a fila de estourados
        "high-fresh",
        "normal-old",
    ]


# --------------------------------------------------------------------------- #
# Color filter: paused is its own bucket
# --------------------------------------------------------------------------- #


def test_color_filter_paused_bucket_is_exclusive() -> None:
    paused = _sla("urgent", minutes_elapsed=600, status="waiting_customer")
    active_red = _sla("urgent", minutes_elapsed=600)

    assert matches_color_filter(paused, "paused")
    assert not matches_color_filter(paused, "yellow")
    assert matches_color_filter(active_red, "red")
    assert not matches_color_filter(active_red, "paused")
