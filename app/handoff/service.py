from app.domain_engine.models import DomainConfig
from app.handoff.models import HandoffDecision


class HandoffService:
    def decide(
        self,
        domain: DomainConfig,
        question: str,
        confidence: float,
    ) -> HandoffDecision:
        reasons: list[str] = []
        normalized_question = question.lower()

        if confidence < domain.handoff.confidence_threshold:
            reasons.append("low_confidence")

        if self._contains_any(normalized_question, domain.handoff.explicit_human_phrases):
            reasons.append("explicit_human_request")

        if self._contains_any(normalized_question, domain.handoff.sensitive_terms):
            reasons.append("sensitive_topic")

        return HandoffDecision(
            escalated=bool(reasons),
            reasons=reasons,
        )

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term.lower() in text for term in terms if term.strip())
