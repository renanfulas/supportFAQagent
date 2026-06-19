from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.conversations.service import ConversationHistoryService
from app.core.config import Settings
from app.core.privacy import hash_sensitive_value
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_UNAVAILABLE,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.schemas import MetaInboundTextMessage
from app.orchestration.chat_flow import ChatFlowService


class MetaWhatsAppChatTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetaWhatsAppChatResult:
    request_id: str
    outbound_message_id: str
    handoff_status: str
    persistence_status: str


class MetaWhatsAppChatTransport:
    def __init__(
        self,
        *,
        settings: Settings,
        database_runtime: DatabaseRuntime,
        client: MetaWhatsAppClient,
        domain_loader: DomainLoader | None = None,
        chat_service: ChatFlowService | None = None,
        repository: OperationalRepository | None = None,
    ) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.client = client
        self.domain_loader = domain_loader or DomainLoader(settings.domains_path)
        self.chat_service = chat_service or ChatFlowService(
            history_service=ConversationHistoryService(database_runtime),
        )
        self.repository = repository or OperationalRepository(database_runtime)

    def handle_text_message(
        self,
        *,
        message: MetaInboundTextMessage,
        request_id: str,
    ) -> MetaWhatsAppChatResult:
        domain = self.domain_loader.load(self.settings.default_domain)
        if domain is None:
            raise MetaWhatsAppChatTransportError("meta_whatsapp_domain_not_found")
        session_id = _safe_meta_session_id(message.from_wa_id)
        response: dict[str, Any] = self.chat_service.answer(
            domain=domain,
            question=message.text,
            session_id=session_id,
            request_id=request_id,
            provider_api_key=None,
            channel="whatsapp",
        )
        persistence = self.repository.record_chat(
            ChatAuditInput(
                request_id=request_id,
                domain=str(response["domain"]),
                session_id=session_id,
                question=message.text,
                answer=str(response["answer"]),
                confidence=float(response["confidence"]),
                escalated=bool(response["escalated"]),
                handoff_reasons=list(response["handoff_reasons"]),
                references=list(response["references"]),
                error_code=response["error_code"],
                channel="whatsapp",
            )
        )
        answer = str(response["answer"])
        if persistence.handoff_status == HANDOFF_UNAVAILABLE:
            answer = (
                f"{answer} O atendimento humano esta temporariamente indisponivel; "
                "guarde o request_id para acompanhamento."
            )
        outbound = self.client.send_text(to=message.from_wa_id, text=answer)
        return MetaWhatsAppChatResult(
            request_id=request_id,
            outbound_message_id=outbound.message_id,
            handoff_status=persistence.handoff_status,
            persistence_status=persistence.persistence_status,
        )


def _safe_meta_session_id(wa_id: str) -> str:
    digest = hash_sensitive_value(wa_id) or "unknown"
    return f"whatsapp:meta:{digest}"
