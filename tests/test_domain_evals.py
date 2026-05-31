from pathlib import Path

import pytest

from app.core.errors import ProviderError
from app.domain_engine.loader import DomainLoader
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner
from app.orchestration.confidence import compute_confidence
from app.retrieval.models import RetrievedChunk


def _force_deterministic_eval_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.service.get_settings",
        lambda: type("Settings", (), {"retrieval_backend": "lexical"})(),
    )

    class FailingWrapper:
        def __init__(self, provider: str, model: str, api_key: str | None = None) -> None:
            _ = (provider, model, api_key)

        def generate_answer(self, prompt: str) -> str:
            _ = prompt
            raise ProviderError("provider unavailable", failure_kind="provider_error")

    monkeypatch.setattr("app.llm.service.LLMWrapper", FailingWrapper)


def test_suporte_vps_whatsapp_eval_suite_loads() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "cases.yaml")

    assert suite is not None
    assert suite.domain == "suporte-vps-whatsapp"
    assert len(suite.cases) >= 6


def test_domain_eval_runner_executes_initial_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_deterministic_eval_runtime(monkeypatch)
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "cases.yaml")
    assert suite is not None

    result = DomainEvalRunner().run(domain=domain, suite=suite)

    assert result.domain == "suporte-vps-whatsapp"
    assert result.total == len(suite.cases)
    assert result.failed == 0
    assert result.passed == result.total


def test_chat_handoff_eval_suite_covers_current_quality_scenarios() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "cases.yaml")
    assert suite is not None

    case_ids = {case.id for case in suite.cases}

    assert "evolution-contexto-forte-docker" in case_ids
    assert "webhook-contexto-fraco-ambiguo" in case_ids
    assert "sensivel-com-orientacao-segura" in case_ids
    assert "pedido-ambiguo-sem-segredo" in case_ids


def test_compute_confidence_weights_strongest_chunk() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    confidence = compute_confidence(
        domain,
        [
            RetrievedChunk(source="a.md", title="A", text="A", score=0.9),
            RetrievedChunk(source="b.md", title="B", text="B", score=0.4),
            RetrievedChunk(source="c.md", title="C", text="C", score=0.3),
        ],
    )

    assert confidence == 0.77
