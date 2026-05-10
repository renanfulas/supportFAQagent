from app.domain_engine.models import DomainConfig
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.retrieval.service import RetrievalService


class ChatFlowService:
    def __init__(self) -> None:
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService()

    def answer(
        self,
        domain: DomainConfig,
        question: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        chunks = self.retrieval_service.retrieve(domain, question)
        confidence = compute_confidence(domain, chunks)
        escalated = confidence < domain.handoff.confidence_threshold

        if not chunks:
            answer = (
                "Nao encontrei contexto suficiente na base atual. "
                "Vale revisar os artigos deste dominio ou escalar para humano."
            )
        else:
            context = "\n\n".join(chunk.text for chunk in chunks)
            prompt = self._build_prompt(domain, question, context, session_id)
            answer = self.llm_service.get_provider(domain).generate_answer(prompt)

        return {
            "domain": domain.name,
            "answer": answer,
            "confidence": confidence,
            "escalated": escalated,
            "references": [chunk.source for chunk in chunks],
        }

    def _build_prompt(
        self,
        domain: DomainConfig,
        question: str,
        context: str,
        session_id: str | None,
    ) -> str:
        session_line = session_id or "anonymous"
        return (
            f"Dominio: {domain.display_name}\n"
            f"Sessao: {session_line}\n"
            f"Tom: {domain.response.tone}\n\n"
            f"Contexto:\n{context}\n\n"
            f"Pergunta:\n{question}\n\n"
            "Responda de forma simples, pratica e segura."
        )
