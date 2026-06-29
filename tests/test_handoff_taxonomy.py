from pathlib import Path

from app.domain_engine.models import DomainConfig
from app.handoff.taxonomy import requires_human_queue, resolve_human_queue


def _domain(*, soft_low_confidence: bool) -> DomainConfig:
    flags = {"soft_low_confidence": True} if soft_low_confidence else {}
    return DomainConfig(
        name="vendas",
        display_name="Vendas",
        root_path=Path("."),
        feature_flags=flags,
    )


def test_requires_human_queue_false_for_low_confidence_only() -> None:
    assert requires_human_queue(["low_confidence"]) is False


def test_requires_human_queue_false_for_empty() -> None:
    assert requires_human_queue([]) is False


def test_requires_human_queue_true_when_a_human_reason_is_present() -> None:
    assert requires_human_queue(["low_confidence", "explicit_human_request"]) is True
    assert requires_human_queue(["sensitive_topic"]) is True
    assert requires_human_queue(["card_data"]) is True


def test_requires_human_queue_true_for_unknown_reason() -> None:
    # An unforeseen/domain-specific reason must never be starved from the queue.
    assert requires_human_queue(["whatsapp_blocking_risk"]) is True


def test_resolve_returns_none_when_flag_off() -> None:
    # Flag off -> caller keeps the legacy behavior (enqueue == escalated).
    assert resolve_human_queue(_domain(soft_low_confidence=False), ["low_confidence"]) is None


def test_resolve_applies_taxonomy_when_flag_on() -> None:
    domain = _domain(soft_low_confidence=True)
    assert resolve_human_queue(domain, ["low_confidence"]) is False
    assert resolve_human_queue(domain, ["explicit_human_request"]) is True
    assert resolve_human_queue(domain, ["low_confidence", "sensitive_topic"]) is True
