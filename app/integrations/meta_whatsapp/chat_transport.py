from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.conversations.service import ConversationHistoryService
from app.conversations.session_state import SessionStateStore
from app.conversations.summary import SummaryRecallService
from app.core.chat_observability import log_chat_completed
from app.core.config import Settings
from app.core.privacy import hash_sensitive_value
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_UNAVAILABLE,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime
from app.handoff.taxonomy import resolve_human_queue
from app.domain_engine.loader import DomainLoader
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.schemas import MetaInboundTextMessage
from app.orchestration.channel_routing import (
    build_domain_router,
    fallback_routing_text,
    resolve_sticky_domain,
)
from app.orchestration.chat_flow import ChatFlowService
from app.orchestration.domain_router import DomainRouter
from app.orchestration.session_domain_store import (
    InMemorySessionDomainStore,
    SessionDomainStore,
)


logger = logging.getLogger(__name__)


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
        router: DomainRouter | None = None,
        session_store: SessionDomainStore | None = None,
        chat_session_state_store: SessionStateStore | None = None,
        last_out_store: SessionDomainStore | None = None,
    ) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.client = client
        # Last routing text sent per session, so a still-ambiguous reply gets the
        # clarification question instead of the same greeting again. Unlike the
        # Hermes transport, only routing turns are recorded here (the Meta path
        # has no general outbound dedup yet).
        self.last_out_store = last_out_store
        self.domain_loader = domain_loader or DomainLoader(settings.domains_path)
        self.chat_service = chat_service or ChatFlowService(
            history_service=ConversationHistoryService(database_runtime),
            session_state_store=(
                chat_session_state_store
                if settings.persistence_backend == "postgres"
                else None
            ),
            summary_recall=(
                SummaryRecallService(database_runtime)
                if settings.persistence_backend == "postgres"
                and settings.enable_summary_recall
                else None
            ),
        )
        self.repository = repository or OperationalRepository(database_runtime)
        self.router = (
            router if router is not None
            else build_domain_router(settings, self.domain_loader)
        )
        # Ephemeral default; the persistence frente can inject a durable store.
        self.session_store = session_store or (
            InMemorySessionDomainStore() if self.router is not None else None
        )

    def handle_text_message(
        self,
        *,
        message: MetaInboundTextMessage,
        request_id: str,
    ) -> MetaWhatsAppChatResult:
        session_id = _safe_meta_session_id(message.from_wa_id)

        if self.router is not None:
            resolution = resolve_sticky_domain(
                router=self.router,
                store=self.session_store,
                default_domain=self.settings.default_domain,
                text=message.text,
                session_id=session_id,
            )
            if resolution.show_menu or resolution.domain is None:
                # Unrouted turn: institutional greeting on first contact, then the
                # clarification question. Status stays "routing_menu" to preserve
                # the observability contract even though the text is conversational.
                last_outbound = (
                    self.last_out_store.get(session_id)
                    if self.last_out_store is not None
                    else None
                )
                text = fallback_routing_text(
                    self.router,
                    last_outbound=last_outbound,
                    reset=resolution.reset,
                )
                if self.last_out_store is not None:
                    self.last_out_store.set(session_id, text)
                outbound = self.client.send_text(
                    to=message.from_wa_id,
                    text=text,
                )
                return MetaWhatsAppChatResult(
                    request_id=request_id,
                    outbound_message_id=outbound.message_id,
                    handoff_status="routing_menu",
                    persistence_status="skipped",
                )
            if resolution.selected:
                outbound = self.client.send_text(
                    to=message.from_wa_id,
                    text=self.router.welcome_text(resolution.domain),
                )
                return MetaWhatsAppChatResult(
                    request_id=request_id,
                    outbound_message_id=outbound.message_id,
                    handoff_status="routing_selected",
                    persistence_status="skipped",
                )
            domain_name = resolution.domain
        else:
            domain_name = self.settings.default_domain

        domain = self.domain_loader.load(domain_name) or self.domain_loader.load(
            self.settings.default_domain
        )
        if domain is None:
            raise MetaWhatsAppChatTransportError("meta_whatsapp_domain_not_found")
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
                requires_human_queue=resolve_human_queue(
                    domain, list(response["handoff_reasons"])
                ),
            )
        )
        log_chat_completed(
            logger,
            request_id=request_id,
            session_id=session_id,
            channel="whatsapp",
            response=response,
            handoff_status=persistence.handoff_status,
            persistence_status=persistence.persistence_status,
            request_id_reused=persistence.request_id_reused,
            settings=self.settings,
        )
        answer = str(response["answer"])
        if persistence.handoff_status == HANDOFF_UNAVAILABLE:
            answer = (
                f"{answer} O atendimento humano está temporariamente indisponível; "
                "guarde o request_id para acompanhamento."
            )
        if persistence.support_deep_link:
            answer = f"{answer}\n\nContinuar no WhatsApp: {persistence.support_deep_link}"
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
