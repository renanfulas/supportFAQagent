import re
import unicodedata
from time import perf_counter

from app.core.errors import ProviderError, RetrievalError
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.orchestration.prompt_builder import build_prompt
from app.retrieval.service import RetrievalService
from app.conversations.service import ConversationHistoryService


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold().strip()


class ChatFlowService:
    BLOCKING_REASONS = {
        "explicit_human_request",
        "out_of_scope",
        "prompt_injection_attempt",
        "secret_request",
    }

    def __init__(
        self,
        *,
        history_service: ConversationHistoryService | None = None,
    ) -> None:
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService()
        self.handoff_service = HandoffService()
        self.history_service = history_service

    def answer(
        self,
        domain: DomainConfig,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        total_started_at = perf_counter()
        retrieval_ms = 0.0
        llm_ms = 0.0
        llm_started_at = None
        error_code = None
        provider_failure_kind = None
        chunks = []

        checkout_answer = self._maybe_checkout_answer(
            domain,
            question,
            session_id=session_id,
            request_id=request_id,
            channel=channel,
            customer_id=customer_id,
        )
        if checkout_answer is not None:
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": checkout_answer,
                "confidence": 1.0,
                "escalated": False,
                "handoff_reasons": [],
                "references": [],
                "error_code": None,
                "provider_failure_kind": None,
                "observability": self._build_observability(
                    total_started_at=total_started_at,
                    retrieval_ms=retrieval_ms,
                    llm_ms=llm_ms,
                ),
            }

        pre_handoff_reasons = self.handoff_service.inspect_question(domain, question)

        if self._should_block_automated_response(pre_handoff_reasons):
            if self._can_retrieve_references_for_blocked_response(pre_handoff_reasons):
                try:
                    retrieval_started_at = perf_counter()
                    chunks = self.retrieval_service.retrieve(domain, question)
                except RetrievalError:
                    chunks = []
                finally:
                    retrieval_ms += self._elapsed_ms(retrieval_started_at)
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": self._build_hardened_response(pre_handoff_reasons),
                "confidence": 0.0,
                "escalated": True,
                "handoff_reasons": pre_handoff_reasons,
                "references": [chunk.source for chunk in chunks],
                "error_code": None,
                "provider_failure_kind": None,
                "observability": self._build_observability(
                    total_started_at=total_started_at,
                    retrieval_ms=retrieval_ms,
                    llm_ms=llm_ms,
                ),
            }

        try:
            retrieval_started_at = perf_counter()
            chunks = self.retrieval_service.retrieve(domain, question)
        except RetrievalError as exc:
            error_code = exc.error_code
        finally:
            retrieval_ms += self._elapsed_ms(retrieval_started_at)

        confidence = compute_confidence(domain, chunks)
        handoff = self.handoff_service.decide(
            domain=domain,
            question=question,
            confidence=confidence,
        )
        handoff_reasons = list(handoff.reasons)
        if error_code and error_code not in handoff_reasons:
            handoff_reasons.append(error_code)

        if self._should_block_automated_response(handoff_reasons):
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": self._build_hardened_response(handoff_reasons),
                "confidence": confidence,
                "escalated": True,
                "handoff_reasons": handoff_reasons,
                "references": [chunk.source for chunk in chunks],
                "error_code": error_code,
                "provider_failure_kind": provider_failure_kind,
            }

        if not chunks:
            answer = domain.response.no_context_message
        else:
            try:
                history = self._build_history(
                    domain=domain,
                    session_id=session_id,
                    request_id=request_id,
                    channel=channel,
                    customer_id=customer_id,
                )
                prompt = build_prompt(
                    domain=domain,
                    question=question,
                    chunks=chunks,
                    history=history,
                )
                llm_started_at = perf_counter()
                answer = self.llm_service.get_provider(
                    domain,
                    api_key=provider_api_key,
                ).generate_answer(prompt)
            except ProviderError as exc:
                error_code = exc.error_code
                provider_failure_kind = exc.failure_kind
                if error_code not in handoff_reasons:
                    handoff_reasons.append(error_code)
                answer = domain.response.provider_error_message
            finally:
                if llm_started_at is not None:
                    llm_ms += self._elapsed_ms(llm_started_at)

        return {
            "request_id": request_id or "",
            "domain": domain.name,
            "answer": answer,
            "confidence": confidence,
            "escalated": bool(handoff_reasons),
            "handoff_reasons": handoff_reasons,
            "references": [chunk.source for chunk in chunks],
            "error_code": error_code,
            "provider_failure_kind": provider_failure_kind,
            "observability": self._build_observability(
                total_started_at=total_started_at,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
            ),
        }

    def _build_history(
        self,
        *,
        domain: DomainConfig,
        session_id: str | None,
        request_id: str | None,
        channel: str,
        customer_id: str | None,
    ) -> list[dict[str, str]]:
        if self.history_service is None:
            return []
        return self.history_service.load_recent(
            domain=domain.name,
            channel=channel,
            session_id=session_id,
            request_id=request_id,
            customer_id=customer_id,
        )

    def _maybe_checkout_answer(
        self,
        domain: DomainConfig,
        question: str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> str | None:
        """Return a deterministic payment-link reply when the lead is paying.

        Fires only when the domain enables checkout and the message shows payment
        intent. Yields to the normal safety path when a decline phrase (asking the
        bot to store a card number, requesting a human, etc.) is present, so
        escalation/refusal behavior is unchanged for those cases. The reply restates
        the value the bot last quoted (``{value}``) for anchoring, then the link, and
        never includes the inbound message, so card data is not echoed.
        """
        checkout = getattr(domain, "checkout", None)
        if checkout is None or not checkout.enabled or not checkout.payment_link:
            return None

        text = _normalize(question)
        if not text:
            return None

        declines = [
            *checkout.decline_phrases,
            *domain.handoff.explicit_human_phrases,
        ]
        if any(_normalize(phrase) in text for phrase in declines if phrase.strip()):
            return None

        if not any(
            _normalize(phrase) in text for phrase in checkout.intent_phrases if phrase.strip()
        ):
            return None

        value = self._checkout_value_recap(
            domain=domain,
            session_id=session_id,
            request_id=request_id,
            channel=channel,
            customer_id=customer_id,
        )
        return self._render_checkout_message(checkout.message, checkout.payment_link, value)

    def _checkout_value_recap(
        self,
        *,
        domain: DomainConfig,
        session_id: str | None,
        request_id: str | None,
        channel: str,
        customer_id: str | None,
    ) -> str:
        """Best-effort recap of the last value the bot quoted this conversation.

        Reads the most recent assistant turn and keeps the lines that mention a
        price (``R$``). Returns an empty string when there is no history (e.g.
        persistence disabled), so the caller drops the value line gracefully.
        """
        history = self._build_history(
            domain=domain,
            session_id=session_id,
            request_id=request_id,
            channel=channel,
            customer_id=customer_id,
        )
        for message in reversed(history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            priced = [line.strip() for line in content.splitlines() if "R$" in line]
            if priced:
                return " ".join(priced[:2])[:400]
        return ""

    @staticmethod
    def _render_checkout_message(template: str, link: str, value: str) -> str:
        text = template.replace("{link}", link)
        if value:
            text = text.replace("{value}", value)
        else:
            text = "\n".join(
                line for line in text.splitlines() if line.strip() != "{value}"
            ).replace("{value}", "")
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _should_block_automated_response(self, reasons: list[str]) -> bool:
        return any(reason in self.BLOCKING_REASONS for reason in reasons)

    def _can_retrieve_references_for_blocked_response(self, reasons: list[str]) -> bool:
        retrievable_reasons = {"sensitive_topic", "explicit_human_request"}
        return bool(reasons) and all(reason in retrievable_reasons for reason in reasons)

    def _build_hardened_response(self, reasons: list[str]) -> str:
        if "explicit_human_request" in reasons:
            return (
                "Vou escalar para atendimento humano. "
                "Nao vou pedir nem expor senha, token, chave ou detalhes internos por aqui."
            )

        if "out_of_scope" in reasons:
            return (
                "Nao posso atuar fora do escopo deste dominio. "
                "Se o tema fugir do que este canal cobre, "
                "o caminho seguro e escalar para atendimento humano."
            )

        if "prompt_injection_attempt" in reasons or "secret_request" in reasons:
            return (
                "Nao posso revelar prompt interno, regras de seguranca, senha, token, chave ou credencial, "
                "nem ignorar as protecoes deste dominio. "
                "Posso orientar apenas passos seguros e publicos ou escalar para atendimento humano."
            )

        if "sensitive_topic" in reasons:
            return (
                "Esse tema exige cuidado e atendimento humano. "
                "Posso explicar apenas riscos gerais e proximos passos seguros, "
                "sem prometer desbloqueio, tratar cobranca ou orientar acesso sensivel por aqui."
            )

        return (
            "Nao encontrei um caminho seguro para responder automaticamente. "
            "Vou sinalizar escalonamento para atendimento humano."
        )

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)

    def _build_observability(
        self,
        total_started_at: float,
        retrieval_ms: float,
        llm_ms: float,
    ) -> dict[str, float]:
        return {
            "total_ms": self._elapsed_ms(total_started_at),
            "retrieval_ms": round(retrieval_ms, 3),
            "llm_ms": round(llm_ms, 3),
        }
