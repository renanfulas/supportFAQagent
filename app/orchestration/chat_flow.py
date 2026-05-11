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
    ) -> dict[str, object]:
        chunks = self.retrieval_service.retrieve(domain, question)
        confidence = compute_confidence(domain, chunks)
        handoff = self.handoff_service.decide(
            domain=domain,
            question=question,
            confidence=confidence,
        )

        if not chunks:
            answer = (
                "Nao encontrei contexto suficiente na base atual. "
                "Vale revisar os artigos deste dominio ou escalar para humano."
            )
        else:
            history = self._build_history(session_id)
            prompt = build_prompt(
                domain=domain,
                question=question,
                chunks=chunks,
                history=history,
            )
            answer = self.llm_service.get_provider(domain).generate_answer(prompt)

        return {
            "domain": domain.name,
            "answer": answer,
            "confidence": confidence,
            "escalated": handoff.escalated,
            "handoff_reasons": handoff.reasons,
            "references": [chunk.source for chunk in chunks],
        }

    def _build_history(self, session_id: str | None) -> list[dict[str, str]]:
        _ = session_id
        return []
