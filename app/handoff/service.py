from app.domain_engine.models import DomainConfig
from app.handoff.models import HandoffDecision


class HandoffService:
    PROMPT_INJECTION_PATTERNS = (
        "ignore suas instrucoes",
        "ignore o contexto",
        "ignore as regras",
        "desconsidere suas instrucoes",
        "desconsidere o contexto",
        "mostre seu prompt",
        "prompt interno",
        "system prompt",
        "revele suas regras",
        "revele suas instrucoes",
        "agora voce e",
        "a partir de agora voce e",
        "finja que voce e",
        "atue como",
        "aja como",
        "voce nao e mais",
        "novo papel",
        "reveal your instructions",
        "bypass",
        "jailbreak",
    )

    SECRET_REQUEST_PATTERNS = (
        "senha",
        "token",
        "chave api",
        "chave da api",
        "api key",
        "credencial",
        "secret",
        "segredo",
        "ssh key",
        "private key",
    )

    def decide(
        self,
        domain: DomainConfig,
        question: str,
        confidence: float,
    ) -> HandoffDecision:
        reasons = self.inspect_question(domain, question)
        normalized_question = question.lower()

        if (
            confidence < domain.handoff.confidence_threshold
            and domain.routing.keywords
            and not self._contains_any(normalized_question, domain.routing.keywords)
        ):
            self._append_reason(reasons, "out_of_scope")

        if confidence < domain.handoff.confidence_threshold:
            self._append_reason(reasons, "low_confidence")

        return HandoffDecision(
            escalated=bool(reasons),
            reasons=reasons,
        )

    def inspect_question(self, domain: DomainConfig, question: str) -> list[str]:
        reasons: list[str] = []
        normalized_question = question.lower()

        if self._contains_any(normalized_question, domain.handoff.explicit_human_phrases):
            self._append_reason(reasons, "explicit_human_request")

        if self._contains_any(normalized_question, domain.handoff.sensitive_terms):
            self._append_reason(reasons, "sensitive_topic")

        if self._contains_any(normalized_question, self.SECRET_REQUEST_PATTERNS):
            self._append_reason(reasons, "secret_request")
            self._append_reason(reasons, "sensitive_topic")

        if self._contains_any(normalized_question, self.PROMPT_INJECTION_PATTERNS):
            self._append_reason(reasons, "prompt_injection_attempt")

        return reasons

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term.lower() in text for term in terms if term.strip())

    def _append_reason(self, reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
