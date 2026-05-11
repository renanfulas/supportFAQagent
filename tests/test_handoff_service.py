from pathlib import Path

from app.domain_engine.models import DomainConfig, DomainHandoffConfig
from app.handoff.service import HandoffService


def make_domain() -> DomainConfig:
    return DomainConfig(
        name="suporte-vps-whatsapp",
        display_name="Suporte VPS e WhatsApp",
        root_path=Path("."),
        handoff=DomainHandoffConfig(
            confidence_threshold=0.7,
            explicit_human_phrases=["falar com humano"],
            sensitive_terms=["senha", "bloqueio"],
        ),
    )


def test_handoff_escalates_on_low_confidence() -> None:
    decision = HandoffService().decide(
        domain=make_domain(),
        question="Como instalar?",
        confidence=0.2,
    )

    assert decision.escalated is True
    assert decision.reasons == ["low_confidence"]


def test_handoff_escalates_on_explicit_human_request() -> None:
    decision = HandoffService().decide(
        domain=make_domain(),
        question="Quero falar com humano",
        confidence=0.95,
    )

    assert decision.escalated is True
    assert "explicit_human_request" in decision.reasons


def test_handoff_escalates_on_sensitive_term() -> None:
    decision = HandoffService().decide(
        domain=make_domain(),
        question="Estou com bloqueio no numero",
        confidence=0.95,
    )

    assert decision.escalated is True
    assert "sensitive_topic" in decision.reasons


def test_handoff_does_not_escalate_when_confident_and_safe() -> None:
    decision = HandoffService().decide(
        domain=make_domain(),
        question="Como instalar a Evolution API?",
        confidence=0.95,
    )

    assert decision.escalated is False
    assert decision.reasons == []
