from pathlib import Path

from app.domain_engine.loader import DomainLoader
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner


def test_suporte_vps_whatsapp_eval_suite_loads() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "cases.yaml")

    assert suite is not None
    assert suite.domain == "suporte-vps-whatsapp"
    assert len(suite.cases) >= 6


def test_domain_eval_runner_executes_initial_suite() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "cases.yaml")
    assert suite is not None

    result = DomainEvalRunner().run(domain=domain, suite=suite)

    assert result.domain == "suporte-vps-whatsapp"
    assert result.total == len(suite.cases)
    assert result.failed == 0
    assert result.passed == result.total
