from app.domain_engine.models import DomainConfig
from app.evals.models import EvalCase, EvalCaseResult, EvalRunResult, EvalSuite
from app.orchestration.chat_flow import ChatFlowService


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
        response = self.chat_flow.answer(
            domain=domain,
            question=case.question,
            request_id=f"eval:{case.id}",
        )
        answer = str(response["answer"]).lower()
        references = [str(reference) for reference in response["references"]]
        handoff_reasons = [str(reason) for reason in response["handoff_reasons"]]
        failures: list[str] = []

        if bool(response["escalated"]) != case.expectation.should_escalate:
            failures.append("unexpected_escalation")

        for term in case.expectation.required_terms:
            if term.lower() not in answer:
                failures.append(f"missing_required_term:{term}")

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
