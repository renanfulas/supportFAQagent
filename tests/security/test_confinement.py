from pathlib import Path

import pytest

from app.core.errors import ProviderError
from app.domain_engine.loader import DomainLoader
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner


def _load_domain():
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None
    return domain


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


def test_confinement_eval_suites_load() -> None:
    domain = _load_domain()
    loader = EvalSuiteLoader()
    suite_dir = domain.root_path / "evals" / "confinement"

    suite_paths = sorted(suite_dir.glob("*.yaml"))
    assert suite_paths

    for suite_path in suite_paths:
        suite = loader.load(suite_path)
        assert suite is not None
        assert suite.domain == domain.name
        assert suite.cases


def test_confinement_eval_suites_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_deterministic_eval_runtime(monkeypatch)
    domain = _load_domain()
    loader = EvalSuiteLoader()
    runner = DomainEvalRunner()
    suite_dir = domain.root_path / "evals" / "confinement"

    for suite_path in sorted(suite_dir.glob("*.yaml")):
        suite = loader.load(suite_path)
        assert suite is not None

        result = runner.run(domain=domain, suite=suite)

        assert result.total == len(suite.cases)
        assert result.failed == 0, suite_path.name
        assert result.passed == result.total
