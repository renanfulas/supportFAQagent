from app.core.errors import ProviderError, RetrievalError
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.orchestration.prompt_builder import build_prompt
from app.retrieval.service import RetrievalService


class ChatFlowService:
    BLOCKING_REASONS = {
        "explicit_human_request",
        "out_of_scope",
        "prompt_injection_attempt",
        "secret_request",
        "sensitive_topic",
    }

    def __init__(self) -> None:
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService()
        self.handoff_service = HandoffService()

    def answer(
        self,
        domain: DomainConfig,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
    ) -> dict[str, object]:
        error_code = None
        chunks = []
        pre_handoff_reasons = self.handoff_service.inspect_question(domain, question)

        if self._should_block_automated_response(pre_handoff_reasons):
            if self._can_retrieve_references_for_blocked_response(pre_handoff_reasons):
                try:
                    chunks = self.retrieval_service.retrieve(domain, question)
                except RetrievalError:
                    chunks = []
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": self._build_hardened_response(pre_handoff_reasons),
                "confidence": 0.0,
                "escalated": True,
                "handoff_reasons": pre_handoff_reasons,
                "references": [chunk.source for chunk in chunks],
                "error_code": None,
            }

        try:
            chunks = self.retrieval_service.retrieve(domain, question)
        except RetrievalError as exc:
            error_code = exc.error_code

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
                history = self._build_history(session_id)
                prompt = build_prompt(
                    domain=domain,
                    question=question,
                    chunks=chunks,
                    history=history,
                )
                answer = self.llm_service.get_provider(
                    domain,
                    api_key=provider_api_key,
                ).generate_answer(prompt)
            except ProviderError as exc:
                error_code = exc.error_code
                if error_code not in handoff_reasons:
                    handoff_reasons.append(error_code)
                answer = domain.response.provider_error_message

        return {
            "request_id": request_id or "",
            "domain": domain.name,
            "answer": answer,
            "confidence": confidence,
            "escalated": bool(handoff_reasons),
            "handoff_reasons": handoff_reasons,
            "references": [chunk.source for chunk in chunks],
            "error_code": error_code,
        }

    def _build_history(self, session_id: str | None) -> list[dict[str, str]]:
        _ = session_id
        return []

    def _should_block_automated_response(self, reasons: list[str]) -> bool:
        return any(reason in self.BLOCKING_REASONS for reason in reasons)

    def _can_retrieve_references_for_blocked_response(self, reasons: list[str]) -> bool:
        return bool(reasons) and all(reason == "sensitive_topic" for reason in reasons)

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
