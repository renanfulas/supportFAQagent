"""Temporary Hermes conversational chat transport.

Mirror of the Meta WhatsApp chat transport, but going through the Hermes bridge
instead of the Meta Graph API. It reuses the same brain (``ChatFlowService``) and
the same domain router + sticky memory, so support and sales behave exactly like
the website and the Meta path.

This is a pilot bridge. The strategic chat channel is Meta WhatsApp Cloud API; keep
Hermes here only while it reduces operational risk, behind ``ENABLE_HERMES_CHAT``.
"""

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
from app.integrations.hermes.client import HermesClient
from app.integrations.hermes.inbound import HermesInboundMessage
from app.orchestration.channel_routing import (
    build_domain_router,
    resolve_sticky_domain,
)
from app.orchestration.chat_flow import ChatFlowService
from app.orchestration.domain_router import DomainRouter
from app.orchestration.session_domain_store import (
    InMemorySessionDomainStore,
    SessionDomainStore,
)


class HermesChatTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class HermesChatResult:
    request_id: str
    outbound_message_id: str
    handoff_status: str
    persistence_status: str


class HermesChatTransport:
    def __init__(
        self,
        *,
        settings: Settings,
        database_runtime: DatabaseRuntime,
        client: HermesClient,
        domain_loader: DomainLoader | None = None,
        chat_service: ChatFlowService | None = None,
        repository: OperationalRepository | None = None,
        router: DomainRouter | None = None,
        session_store: SessionDomainStore | None = None,
    ) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.client = client
        self.domain_loader = domain_loader or DomainLoader(settings.domains_path)
        self.chat_service = chat_service or ChatFlowService(
            history_service=ConversationHistoryService(database_runtime),
        )
        self.repository = repository or OperationalRepository(database_runtime)
        self.router = (
            router if router is not None
            else build_domain_router(settings, self.domain_loader)
        )
        self.session_store = session_store or (
            InMemorySessionDomainStore() if self.router is not None else None
        )

    def handle_text_message(
        self,
        *,
        message: HermesInboundMessage,
        request_id: str,
    ) -> HermesChatResult:
        session_id = _safe_hermes_session_id(message.from_wa_id)

        if self.router is not None:
            domain_name = resolve_sticky_domain(
                router=self.router,
                store=self.session_store,
                default_domain=self.settings.default_domain,
                text=message.text,
                session_id=session_id,
            )
            if domain_name is None:
                outbound = self.client.send_text(
                    to=message.from_wa_id,
                    text=self.router.menu_text(),
                    message_id=message.message_id,
                )
                return HermesChatResult(
                    request_id=request_id,
                    outbound_message_id=outbound.message_id,
                    handoff_status="routing_menu",
                    persistence_status="skipped",
                )
        else:
            domain_name = self.settings.default_domain

        domain = self.domain_loader.load(domain_name) or self.domain_loader.load(
            self.settings.default_domain
        )
        if domain is None:
            raise HermesChatTransportError("hermes_domain_not_found")
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
        outbound = self.client.send_text(
            to=message.from_wa_id,
            text=answer,
            message_id=message.message_id,
        )
        return HermesChatResult(
            request_id=request_id,
            outbound_message_id=outbound.message_id,
            handoff_status=persistence.handoff_status,
            persistence_status=persistence.persistence_status,
        )


def _safe_hermes_session_id(wa_id: str) -> str:
    digest = hash_sensitive_value(wa_id) or "unknown"
    return f"whatsapp:hermes:{digest}"
