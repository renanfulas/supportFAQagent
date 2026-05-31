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
        "qual a senha",
        "me passe a senha",
        "envie a senha",
        "manda a senha",
        "me passa o token",
        "envie o token",
        "me passe o token",
        "qual o token",
        "me passe a chave api",
        "envie a chave api",
        "qual a chave api",
        "me passe a credencial",
        "envie a credencial",
        "qual a credencial",
        "me passe o secret",
        "me passe o segredo",
        "envie o segredo",
        "private key",
        "ssh key",
        "me passe a ssh key",
        "me passe a private key",
    )

    BENIGN_AUTH_CONTEXT_PATTERNS = (
        "continua pedindo senha",
        "aparece permission denied publickey",
        "permission denied publickey",
        "permission denied (publickey)",
        "cadastrei uma chave ssh",
        "chave ssh nao funciona",
    )

    CRITICAL_OPERATIONAL_PATTERNS = (
        "mudei a porta do ssh",
        "mudei a porta ssh",
        "bloqueei a porta ssh",
        "bloqueei a porta do ssh",
        "nao responde ping",
        "todos os sites ficaram fora do ar",
        "perdi acesso total",
        "nao inicializa mais",
        "suspeito de malware",
        "suspeito de minerador",
        "alerta de seguranca",
        "receio de vazamento",
        "consumo alto e suspeito",
        "modo rescue",
        "modo recovery",
        "rescue ou recovery",
    )

    AMBIGUOUS_PATTERNS = (
        "nao funciona",
        "deu erro",
        "travou",
        "parou",
        "bloqueou",
        "caiu",
        "o que faco",
        "como resolvo",
    )

    def decide(
        self,
        domain: DomainConfig,
        question: str,
        confidence: float,
    ) -> HandoffDecision:
        reasons = self.inspect_question(domain, question)
        normalized_question = question.lower()

        has_domain_signal = self._has_domain_signal(domain, normalized_question)
        if (
            confidence < domain.handoff.confidence_threshold
            and not has_domain_signal
            and not reasons
        ):
            self._append_reason(reasons, "out_of_scope")

        if self._is_critical_operational_case(normalized_question):
            self._append_reason(reasons, "low_confidence")
        elif confidence < domain.handoff.confidence_threshold:
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

        if (
            self._contains_any(normalized_question, domain.handoff.sensitive_terms)
            and not self._is_benign_auth_context(normalized_question)
        ):
            self._append_reason(reasons, "sensitive_topic")

        if self._contains_any(normalized_question, self.SECRET_REQUEST_PATTERNS):
            self._append_reason(reasons, "secret_request")
            self._append_reason(reasons, "sensitive_topic")

        if self._contains_any(normalized_question, self.PROMPT_INJECTION_PATTERNS):
            self._append_reason(reasons, "prompt_injection_attempt")

        return reasons

    def _has_domain_signal(self, domain: DomainConfig, text: str) -> bool:
        domain_terms = [
            *domain.routing.keywords,
            domain.name,
            domain.display_name,
        ]

        normalized_terms = self._expand_domain_terms(domain_terms)
        if self._contains_any(text, normalized_terms):
            return True

        return self._contains_any(text, self.AMBIGUOUS_PATTERNS) and self._contains_any(
            text,
            [term for term in normalized_terms if len(term) >= 4],
        )

    def _is_benign_auth_context(self, text: str) -> bool:
        return self._contains_any(text, self.BENIGN_AUTH_CONTEXT_PATTERNS)

    def _is_critical_operational_case(self, text: str) -> bool:
        return self._contains_any(text, self.CRITICAL_OPERATIONAL_PATTERNS)

    def _expand_domain_terms(self, terms: list[str]) -> list[str]:
        expanded_terms: list[str] = []
        for term in terms:
            normalized = term.strip().lower()
            if not normalized:
                continue

            expanded_terms.append(normalized)
            expanded_terms.extend(
                part
                for part in normalized.replace("-", " ").split()
                if len(part) >= 4
            )

        return list(dict.fromkeys(expanded_terms))

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term.lower() in text for term in terms if term.strip())

    def _append_reason(self, reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
