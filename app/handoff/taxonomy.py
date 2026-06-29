"""Reason taxonomy for handoff: which reasons actually need a human in the queue.

A turn can be escalated (a flag was raised) without a person needing to pick it up.
``low_confidence`` is the lone SOFT_SIGNAL: it stays logged and keeps ``escalated``
true, but on its own it must not enqueue a human handoff (that is what floods the
queue in production). Any other reason -- an explicit human request, a sensitive
topic, secret/card data, a domain-specific escalation rule, or a provider/error
code -- is treated as needing the human queue, so the queue is never starved for an
unforeseen reason.

This lives in ``app/handoff`` so web, Meta and Hermes share one definition.
"""

from __future__ import annotations

from app.domain_engine.models import DomainConfig


SOFT_LOW_CONFIDENCE_FLAG = "soft_low_confidence"

# The only reasons that, on their own, do NOT warrant a human-queue entry.
SOFT_SIGNAL_REASONS = frozenset({"low_confidence"})


def requires_human_queue(reasons: list[str]) -> bool:
    """True when at least one reason is not a pure soft signal.

    An empty reason list or a list containing only ``low_confidence`` returns
    ``False``; anything else (including unknown reasons) returns ``True`` so the
    human queue is never starved.
    """
    return any(reason not in SOFT_SIGNAL_REASONS for reason in reasons)


def resolve_human_queue(domain: DomainConfig, reasons: list[str]) -> bool | None:
    """Decide whether a turn needs the human queue, honoring the per-domain flag.

    Returns ``None`` when the ``soft_low_confidence`` flag is off, so the caller
    keeps the legacy behavior (enqueue == ``escalated``). With the flag on, returns
    the taxonomy decision so a ``low_confidence``-only turn stops flooding the queue.
    """
    if not domain.is_flag_enabled(SOFT_LOW_CONFIDENCE_FLAG):
        return None
    return requires_human_queue(reasons)
