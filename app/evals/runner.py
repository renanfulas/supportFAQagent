import unicodedata

from app.domain_engine.models import DomainConfig
from app.evals.models import EvalCase, EvalCaseResult, EvalRunResult, EvalSuite
from app.orchestration.chat_flow import ChatFlowService


def _fold(text: str) -> str:
    """Casefold and strip accents so term matching ignores orthography.

    Answers are written in proper pt-BR ("não posso"), while eval terms may be
    ASCII ("nao posso") or accented; both must keep matching.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold()


class _StaticSummaryRecall:
    """Recall stub that returns the case's seeded summary (tiering Fase 4).

    Duck-types ``SummaryRecallService.latest_for`` so the case exercises the
    real recall path in ``ChatFlowService`` (including the
    ``ENABLE_SUMMARY_RECALL`` gate and the untrusted prompt block) without
    needing a warehouse row.
    """

    def __init__(self, summary: str) -> None:
        self._summary = summary

    def latest_for(self, *, domain: str, customer_ref: str | None) -> str | None:
        _ = (domain, customer_ref)
        return self._summary


class DomainEvalRunner:
    def __init__(self, chat_flow: ChatFlowService | None = None) -> None:
        self.chat_flow = chat_flow or ChatFlowService()

    def run(self, domain: DomainConfig, suite: EvalSuite) -> EvalRunResult:
        results = [
            self._run_case(domain=domain, case=case)
            for case in suite.cases
        ]
        passed = sum(1 for result in results if result.passed)

        return EvalRunResult(
            domain=domain.name,
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
        )

    def _run_case(self, domain: DomainConfig, case: EvalCase) -> EvalCaseResult:
        response = self._answer_case(domain=domain, case=case)
        answer = _fold(str(response["answer"]))
        references = [str(reference) for reference in response["references"]]
        handoff_reasons = [str(reason) for reason in response["handoff_reasons"]]
        failures: list[str] = []

        if bool(response["escalated"]) != case.expectation.should_escalate:
            failures.append("unexpected_escalation")

        for term in case.expectation.required_terms:
            if _fold(term) not in answer:
                failures.append(f"missing_required_term:{term}")

        for term in case.expectation.forbidden_terms:
            if _fold(term) in answer:
                failures.append(f"forbidden_term_present:{term}")

        for expected_reference in case.expectation.expected_references:
            if not any(expected_reference in reference for reference in references):
                failures.append(f"missing_reference:{expected_reference}")

        if case.expectation.allowed_handoff_reasons:
            unexpected_reasons = [
                reason
                for reason in handoff_reasons
                if reason not in case.expectation.allowed_handoff_reasons
            ]
            for reason in unexpected_reasons:
                failures.append(f"unexpected_handoff_reason:{reason}")

        return EvalCaseResult(
            case_id=case.id,
            passed=not failures,
            failures=failures,
            escalated=bool(response["escalated"]),
            confidence=float(response["confidence"]),
            handoff_reasons=handoff_reasons,
            references=references,
        )

    def _answer_case(self, *, domain: DomainConfig, case: EvalCase) -> dict:
        if case.customer_summary is None:
            return self.chat_flow.answer(
                domain=domain,
                question=case.question,
                request_id=f"eval:{case.id}",
            )
        # Seeded-summary case: swap the recall source for this case only, and
        # give the flow a customer ref so the recall path actually fires. The
        # ENABLE_SUMMARY_RECALL gate still applies inside the flow -- the suite
        # is meant to run against the same config the live channel uses.
        original_recall = self.chat_flow.summary_recall
        self.chat_flow.summary_recall = _StaticSummaryRecall(case.customer_summary)
        try:
            return self.chat_flow.answer(
                domain=domain,
                question=case.question,
                request_id=f"eval:{case.id}",
                customer_id=f"eval-customer:{case.id}",
            )
        finally:
            self.chat_flow.summary_recall = original_recall
