from app.core.errors import ProviderError, RetrievalError
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.orchestration.prompt_builder import build_prompt
from app.retrieval.service import RetrievalService


class ChatFlowService:
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
    ) -> dict[str, object]:
        error_code = None
        chunks = []

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

        if not chunks:
            answer = (
                "Nao encontrei contexto suficiente na base atual. "
                "Vale revisar os artigos deste dominio ou escalar para humano."
            )
        else:
            try:
                history = self._build_history(session_id)
                prompt = build_prompt(
                    domain=domain,
                    question=question,
                    chunks=chunks,
                    history=history,
                )
                answer = self.llm_service.get_provider(domain).generate_answer(prompt)
            except ProviderError as exc:
                error_code = exc.error_code
                if error_code not in handoff_reasons:
                    handoff_reasons.append(error_code)
                answer = (
                    "Nao consegui gerar uma resposta automatica agora. "
                    "Escalando para atendimento humano."
                )

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
