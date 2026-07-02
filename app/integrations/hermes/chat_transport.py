"""Temporary Hermes conversational chat transport.

Mirror of the Meta WhatsApp chat transport, but going through the Hermes bridge
instead of the Meta Graph API. It reuses the same brain (``ChatFlowService``) and
the same domain router + sticky memory, so support and sales behave exactly like
the website and the Meta path.

This is a pilot bridge. The strategic chat channel is Meta WhatsApp Cloud API; keep
Hermes here only while it reduces operational risk, behind ``ENABLE_HERMES_CHAT``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.conversations.service import ConversationHistoryService
from app.core.chat_observability import log_chat_completed
from app.core.config import Settings
from app.core.privacy import hash_sensitive_value
from app.core.rate_limit import InMemoryRateLimiter, RateLimitExceeded
from app.db.operational import (
    ChatAuditInput,
    HANDOFF_UNAVAILABLE,
    OperationalRepository,
)
from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from app.handoff.taxonomy import resolve_human_queue
from app.integrations.hermes.client import HermesClient
from app.integrations.hermes.inbound import HermesInboundMessage
from app.orchestration.channel_routing import (
    build_domain_router,
    fallback_routing_text,
    resolve_sticky_domain,
)
from app.conversations.session_state import SessionStateStore
from app.conversations.summary import SummaryRecallService
from app.orchestration.chat_flow import ChatFlowService
from app.orchestration.domain_router import DomainRouter
from app.orchestration.session_domain_store import (
    InMemorySessionDomainStore,
    SessionDomainStore,
)


logger = logging.getLogger(__name__)


class HermesChatTransportError(RuntimeError):
    pass


# Shared across per-request transports so the per-number limit actually holds.
_rate_limiter: InMemoryRateLimiter | None = None


def _shared_rate_limiter(max_per_minute: int) -> InMemoryRateLimiter:
    global _rate_limiter
    if _rate_limiter is None or _rate_limiter.max_requests != max_per_minute:
        _rate_limiter = InMemoryRateLimiter(max_requests=max_per_minute, window_seconds=60)
    return _rate_limiter


ESCAPE_STATE = "awaiting_escape"
ESCAPE_OPTIONS = "\n\n1) Resolver com um atendente\n2) Encerrar atendimento"
REPEAT_NUDGE = (
    "Acho que me embolei aqui. Pra eu te ajudar melhor, me conta em uma frase: "
    "qual o tipo de site, o objetivo e quantas visitas você espera por dia? "
    "Com isso eu já te indico o plano certo e a gente fecha."
)
MSG_TO_HUMAN = (
    "Certo! Vou te transferir para um atendente humano. "
    "Em instantes alguém continua o atendimento por aqui."
)
MSG_CLOSED = (
    "Atendimento encerrado. Quando precisar, é só mandar um *oi* que eu "
    "recomeço por aqui. Até logo!"
)


def _escape_choice(text: str) -> str:
    normalized = text.strip().lower()
    if normalized == "1" or "atendente" in normalized:
        return "1"
    if normalized == "2" or "encerrar" in normalized:
        return "2"
    return ""


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
        state_store: SessionDomainStore | None = None,
        last_out_store: SessionDomainStore | None = None,
        chat_session_state_store: SessionStateStore | None = None,
        rate_limiter: InMemoryRateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.client = client
        # Per-session conversational state (e.g. waiting for the escape choice).
        # When absent, the escape-options feature is inactive.
        self.state_store = state_store
        # Last outbound text per session, to avoid sending the exact same message
        # twice in a row (which is the symptom of a stuck conversation).
        self.last_out_store = last_out_store
        self.rate_limiter = rate_limiter or _shared_rate_limiter(
            settings.whatsapp_chat_rate_limit_per_minute
        )
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

        try:
            self.rate_limiter.check(session_id)
        except RateLimitExceeded:
            # Drop the excess silently: no LLM call, no outbound burst. Protects cost
            # and reduces spam-ban risk on the unofficial bridge.
            return HermesChatResult(
                request_id=request_id,
                outbound_message_id="",
                handoff_status="rate_limited",
                persistence_status="skipped",
            )

        # If the session was offered the escape options, interpret 1/2 here.
        if self.state_store is not None and self.state_store.get(session_id) == ESCAPE_STATE:
            choice = _escape_choice(message.text)
            if choice == "1":
                self.state_store.clear(session_id)
                return self._reply(message, MSG_TO_HUMAN, request_id, "human_requested")
            if choice == "2":
                self.state_store.clear(session_id)
                if self.session_store is not None:
                    self.session_store.clear(session_id)
                if self.last_out_store is not None:
                    self.last_out_store.clear(session_id)
                return self._reply(message, MSG_CLOSED, request_id, "closed")
            # Any other reply cancels the prompt and is handled as a normal message.
            self.state_store.clear(session_id)

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
                return self._send_dedup(
                    session_id=session_id,
                    message=message,
                    text=fallback_routing_text(
                        self.router,
                        last_outbound=last_outbound,
                        reset=resolution.reset,
                    ),
                    request_id=request_id,
                    status="routing_menu",
                )
            if resolution.selected:
                return self._send_dedup(
                    session_id=session_id,
                    message=message,
                    text=self.router.welcome_text(resolution.domain),
                    request_id=request_id,
                    status="routing_selected",
                )
            domain_name = resolution.domain
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
        # When the bot cannot help (out of scope), offer a clear escape and remember
        # we are waiting for the choice.
        if self.state_store is not None and "out_of_scope" in response["handoff_reasons"]:
            answer = answer + ESCAPE_OPTIONS
            self.state_store.set(session_id, ESCAPE_STATE)
        return self._send_dedup(
            session_id=session_id,
            message=message,
            text=answer,
            request_id=request_id,
            status=persistence.handoff_status,
            persistence_status=persistence.persistence_status,
        )

    def _reply(
        self,
        message: HermesInboundMessage,
        text: str,
        request_id: str,
        status: str,
    ) -> HermesChatResult:
        outbound = self.client.send_text(
            to=message.chat_id,
            text=text,
            message_id=message.message_id,
        )
        return HermesChatResult(
            request_id=request_id,
            outbound_message_id=outbound.message_id,
            handoff_status=status,
            persistence_status="skipped",
        )

    def _send_dedup(
        self,
        *,
        session_id: str,
        message: HermesInboundMessage,
        text: str,
        request_id: str,
        status: str,
        persistence_status: str = "skipped",
    ) -> HermesChatResult:
        store = self.last_out_store
        if store is not None:
            if store.get(session_id) == text:
                # Would repeat the exact same message to the same person: stop, and
                # re-engage with a reflection that moves the conversation forward.
                text, status = REPEAT_NUDGE, "repeat_reflection"
                persistence_status = "skipped"
            store.set(session_id, text)
        outbound = self.client.send_text(
            to=message.chat_id,
            text=text,
            message_id=message.message_id,
        )
        return HermesChatResult(
            request_id=request_id,
            outbound_message_id=outbound.message_id,
            handoff_status=status,
            persistence_status=persistence_status,
        )


def _safe_hermes_session_id(wa_id: str) -> str:
    digest = hash_sensitive_value(wa_id) or "unknown"
    return f"whatsapp:hermes:{digest}"
