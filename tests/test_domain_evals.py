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


def test_summary_recall_suite_loads() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "summary_recall.yaml")

    assert suite is not None
    assert suite.domain == "suporte-vps-whatsapp"
    assert all(case.customer_summary for case in suite.cases)
    # The "does not pollute" cases must carry a negative assertion.
    polui = [case for case in suite.cases if "nao-polui" in case.id]
    assert polui
    assert all(case.expectation.forbidden_terms for case in polui)


class _FakeChatFlow:
    """Minimal chat-flow double: records calls, echoes a scripted answer."""

    def __init__(self, answer_text: str) -> None:
        self.answer_text = answer_text
        self.summary_recall = None
        self.calls: list[dict] = []

    def answer(self, *, domain, question, request_id, customer_id=None):
        recalled = None
        if self.summary_recall is not None:
            recalled = self.summary_recall.latest_for(
                domain=domain.name, customer_ref=customer_id
            )
        self.calls.append({"customer_id": customer_id, "recalled": recalled})
        return {
            "answer": self.answer_text,
            "references": [],
            "handoff_reasons": ["low_confidence"],
            "escalated": True,
            "confidence": 0.4,
        }


def _summary_case(**overrides):
    from app.evals.models import EvalCase

    payload = {
        "id": "recall-caso",
        "category": "summary_recall",
        "question": "Mudei a porta do SSH e perdi o acesso a VPS.",
        "customer_summary": "Problema: porta 2222 bloqueada. | Solucao: liberar no firewall. | Status: resolvido.",
        "expectation": {
            "should_escalate": True,
            "allowed_handoff_reasons": ["low_confidence"],
        },
    }
    payload.update(overrides)
    return EvalCase(**payload)


def test_runner_injects_case_summary_and_restores_recall() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None
    chat_flow = _FakeChatFlow(answer_text="verifique a porta 2222 no firewall")
    runner = DomainEvalRunner(chat_flow=chat_flow)

    result = runner._run_case(domain=domain, case=_summary_case())

    assert result.passed
    call = chat_flow.calls[0]
    # The recall stub fed the case's summary and a customer ref was supplied so
    # the real flow's recall path fires.
    assert call["recalled"].startswith("Problema: porta 2222")
    assert call["customer_id"] == "eval-customer:recall-caso"
    # The runner's chat flow is clean again for the next (summary-less) case.
    assert chat_flow.summary_recall is None


def test_runner_flags_forbidden_term_in_answer() -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None
    chat_flow = _FakeChatFlow(answer_text="resposta com ABRACADABRA123 vazado")
    runner = DomainEvalRunner(chat_flow=chat_flow)

    case = _summary_case(
        expectation={
            "should_escalate": True,
            "forbidden_terms": ["abracadabra"],
            "allowed_handoff_reasons": ["low_confidence"],
        }
    )
    result = runner._run_case(domain=domain, case=case)

    assert not result.passed
    assert "forbidden_term_present:abracadabra" in result.failures


def test_summary_recall_reaches_prompt_through_real_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end on the deterministic trail: the seeded summary must travel
    ChatFlowService._recall_customer_summary -> build_prompt (untrusted block).
    The fake provider answers with the summary's detail only when it sees it in
    the prompt, so a green case proves the injection mechanics."""

    _force_deterministic_eval_runtime(monkeypatch)

    prompts: list[str] = []

    class EchoWrapper:
        def __init__(self, provider: str, model: str, api_key: str | None = None) -> None:
            _ = (provider, model, api_key)

        def generate_answer(self, prompt: str) -> str:
            prompts.append(prompt)
            if "2222" in prompt:
                return "Confira se a porta 2222 esta liberada no firewall."
            return "Confira a configuracao de SSH."

    monkeypatch.setattr("app.llm.service.LLMWrapper", EchoWrapper)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type(
            "Settings",
            (),
            {"enable_summary_recall": True, "persistence_hash_secret": ""},
        )(),
    )

    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None
    suite = EvalSuiteLoader().load(domain.root_path / "evals" / "summary_recall.yaml")
    assert suite is not None
    melhora = next(
        case for case in suite.cases if case.id == "recall-melhora-continuidade-ssh"
    )

    result = DomainEvalRunner()._run_case(domain=domain, case=melhora)

    assert result.passed, result.failures
    # The summary text landed inside the untrusted customer-history block.
    assert "<untrusted_customer_history>" in prompts[0]
    assert "porta padrao para 2222" in prompts[0]


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
