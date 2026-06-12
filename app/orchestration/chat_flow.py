from time import perf_counter

from app.core.errors import ProviderError, RetrievalError
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.orchestration.prompt_builder import build_prompt
from app.retrieval.service import RetrievalService
from app.conversations.service import ConversationHistoryService


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
    ) -> dict[str, object]:
        total_started_at = perf_counter()
        retrieval_ms = 0.0
        llm_ms = 0.0
        llm_started_at = None
        error_code = None
        chunks = []
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
    ) -> list[dict[str, str]]:
        if self.history_service is None:
            return []
        return self.history_service.load_recent(
            domain=domain.name,
            channel=channel,
            session_id=session_id,
            request_id=request_id,
        )

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
                "Se o tema nao for sobre VPS, WhatsApp, Evolution API, n8n ou automacoes relacionadas, "
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
