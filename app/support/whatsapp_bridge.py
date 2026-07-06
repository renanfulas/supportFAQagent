"""Numero de suporte: handler de inbound sem RAG (ponte WhatsApp<->console).

Modo-por-numero (decisao central da frente): mensagens que chegam no numero de
suporte NUNCA passam pelo RAG/roteador de dominio -- isso e o que elimina a
corrida bot-vs-humano de graca, sem estado nem lock. O thin bot so RESPONDE a
um inbound, nunca inicia, o que garante que toda resposta automatica cai
dentro da janela de 24h da Meta (nunca precisa de template).

Numero handoff-only: so existe caso ligado a um token de deep link ou a um
wa_id ja vinculado. Sem isso, nao ha triagem por design -- ver
docs/quality-plans/whatsapp-support-bridge-tech-plan.md.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.logging import log_event
from app.core.persistence_sanitize import REDACTION_VERSION, sanitize_for_persistence
from app.db.runtime import DatabaseRuntime
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.schemas import (
    MetaInboundTextMessage,
    MetaMessageStatus,
)
from app.support.wa_binding import CaseWhatsAppBindingRepository, resolve_case_token


logger = logging.getLogger(__name__)

# Deep-link token shape minted by wa_binding.mint_case_token: "case.<uuid>.<sig>".
_TOKEN_PATTERN = re.compile(
    r"case\.[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.[A-Za-z0-9_-]+"
)

_OPEN_CASE_STATUSES = ("open", "in_progress", "waiting_customer")
_HUMAN_TAKEOVER_STATUSES = ("bot", "handoff_pending")

_NOT_FOUND_TEXT = (
    "Nao encontrei um atendimento vinculado a este numero. Use o link enviado "
    "pelo assistente para continuar seu chamado."
)
_ACK_TEXT_TEMPLATE = "Seu chamado foi passado para um atendente. Ele responde e resolve por aqui."
_OUT_OF_HOURS_SUFFIX = (
    " Nosso time atende de {days_label} das {start} as {end} ({timezone}); "
    "retornamos assim que voltarmos."
)


@dataclass(frozen=True)
class SupportInboundResult:
    case_id: str | None
    bound: bool
    acked: bool


@dataclass(frozen=True)
class SendReplyResult:
    message_id: str
    delivery: str  # "freeform" | "template"


class CaseHasNoBinding(Exception):
    """The case has no live WhatsApp binding (customer never contacted the
    support number, or the binding was purged on close/expiry)."""


class SupportWhatsAppWindowClosed(Exception):
    """The 24h Meta customer-service window is closed (best-effort mirror);
    a free-form send would likely be rejected. The caller should offer a
    template instead."""


class UnknownStaffTemplate(Exception):
    """``template`` is not in ALLOWED_STAFF_TEMPLATES -- distinct from a
    generic ValueError (e.g. empty message) so the route can tell the two
    apart and return the right error code."""


# Fase 2: templates the STAFF can trigger manually from the compositor when
# the window is closed. ``atendente_assumiu`` and ``ticket_resolvido`` are
# system-triggered on transitions (app/support/transitions.py), never chosen
# by the operator here -- keeping the two paths distinct matches the
# contract table in the tech plan.
ALLOWED_STAFF_TEMPLATES = frozenset({"precisa_info", "reengajar"})

ALL_TEMPLATE_LABELS = frozenset(
    {"atendente_assumiu", "precisa_info", "ticket_resolvido", "reengajar"}
)


def resolve_template_name(label: str, *, settings: Settings) -> str:
    """Map an internal template label to the name approved on the WABA.

    Defaults to the label itself (works out of the box in dev/tests); a
    production deploy overrides via ``SUPPORT_WA_TEMPLATE_*`` once Meta
    approves the templates, possibly under different names -- no code change
    needed.
    """

    mapping = {
        "atendente_assumiu": settings.support_wa_template_atendente_assumiu,
        "precisa_info": settings.support_wa_template_precisa_info,
        "ticket_resolvido": settings.support_wa_template_ticket_resolvido,
        "reengajar": settings.support_wa_template_reengajar,
    }
    return mapping.get(label, label)


class SupportWhatsAppBridgeService:
    def __init__(
        self,
        *,
        settings: Settings,
        database_runtime: DatabaseRuntime,
        client: MetaWhatsAppClient,
        bindings: CaseWhatsAppBindingRepository | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.client = client
        self.bindings = bindings or CaseWhatsAppBindingRepository(
            database_runtime, enc_key=settings.support_wa_enc_key or ""
        )
        self._now = now or (lambda: datetime.now(UTC))

    def handle_inbound(
        self,
        message: MetaInboundTextMessage,
        *,
        request_id: str,
    ) -> SupportInboundResult:
        case_id = self._resolve_case_id(message)
        if case_id is None:
            self.client.send_text(to=message.from_wa_id, text=_NOT_FOUND_TEXT)
            log_event(logger, "support_wa_inbound_unmatched", request_id=request_id)
            return SupportInboundResult(case_id=None, bound=False, acked=True)

        now = self._now()
        first_contact = self.bindings.get(case_id) is None
        self.bindings.bind(
            case_id=case_id,
            wa_id=message.from_wa_id,
            max_days=self.settings.support_wa_binding_max_days,
            now=now,
        )
        self.bindings.touch_customer_message(case_id=case_id, now=now)
        self._append_message(
            case_id=case_id,
            role="user",
            content=message.text,
            actor_kind="customer",
        )

        acked = False
        within_hours = self._within_business_hours(now)
        if first_contact or not within_hours:
            self.client.send_text(
                to=message.from_wa_id,
                text=self._thin_bot_text(first_contact=first_contact, within_hours=within_hours),
            )
            acked = True

        log_event(
            logger,
            "support_wa_inbound",
            request_id=request_id,
            case_id=case_id,
            first_contact=first_contact,
            within_business_hours=within_hours,
        )
        return SupportInboundResult(case_id=case_id, bound=True, acked=acked)

    def send_agent_reply(
        self,
        *,
        case_id: str,
        staff_id: str,
        text: str,
        template: str | None = None,
    ) -> SendReplyResult:
        """Compositor do atendente: append the reply, then enqueue delivery.

        Inside the window, free-form always wins (it's free; a ``template``
        argument is ignored there on purpose -- no point paying for a
        template when a normal message works). Outside the window, a
        ``template`` from ``ALLOWED_STAFF_TEMPLATES`` is required; without
        one, raises ``SupportWhatsAppWindowClosed`` so the caller can offer
        the available templates instead of silently failing.
        """

        binding = self.bindings.get(case_id)
        if binding is None:
            raise CaseHasNoBinding(case_id)

        window_open = self.bindings.is_window_open(
            binding, window_hours=self.settings.support_wa_window_hours
        )
        if not window_open:
            if template is None:
                raise SupportWhatsAppWindowClosed(case_id)
            if template not in ALLOWED_STAFF_TEMPLATES:
                raise UnknownStaffTemplate(template)

        message_id = self._append_message(
            case_id=case_id,
            role="agent",
            content=text,
            actor_kind="staff",
            actor_staff_id=staff_id,
        )
        if message_id is None:
            raise ValueError("empty_message")

        if window_open:
            self._enqueue_send(
                case_id=case_id,
                message_id=message_id,
                to=binding.wa_id,
                text=text,
            )
            return SendReplyResult(message_id=message_id, delivery="freeform")

        self._enqueue_template(
            case_id=case_id,
            message_id=message_id,
            to=binding.wa_id,
            template=template,
        )
        return SendReplyResult(message_id=message_id, delivery="template")

    def _enqueue_send(self, *, case_id: str, message_id: str, to: str, text: str) -> None:
        # `to` is written verbatim (not through sanitize_payload, which would
        # redact a phone-shaped string) so the dispatcher can deliver it --
        # same deliberate exemption as app/notifications/support_team.py.
        payload = json.dumps(
            {
                "to": to,
                "text": text,
                "support_case_id": case_id,
                "message_row_id": message_id,
                "phone_number_kind": "support",
            }
        )
        with self.database_runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO operational_outbox (
                      event_type, idempotency_key, request_id, payload_sanitized
                    )
                    VALUES ('whatsapp.message.requested', %s, %s, %s::jsonb)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (f"support_wa_send:{message_id}", case_id, payload),
                )

    def _enqueue_template(
        self, *, case_id: str, message_id: str, to: str, template: str
    ) -> None:
        payload = json.dumps(
            {
                "to": to,
                "template_name": resolve_template_name(template, settings=self.settings),
                "language_code": self.settings.support_wa_template_language,
                "support_case_id": case_id,
                "message_row_id": message_id,
                "phone_number_kind": "support",
            }
        )
        with self.database_runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO operational_outbox (
                      event_type, idempotency_key, request_id, payload_sanitized
                    )
                    VALUES ('whatsapp.template.requested', %s, %s, %s::jsonb)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (f"support_wa_template:{message_id}", case_id, payload),
                )

    def _resolve_case_id(self, message: MetaInboundTextMessage) -> str | None:
        existing = self.bindings.find_open_case_id_by_wa_id(message.from_wa_id)
        if existing is not None and self._case_is_open(existing):
            return existing
        token = _extract_token(message.text)
        if token is None:
            return None
        case_id = resolve_case_token(token, secret=self.settings.support_wa_token_secret or "")
        if case_id is None or not self._case_is_open(case_id):
            return None
        return case_id

    def _case_is_open(self, case_id: str) -> bool:
        with self.database_runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM support_cases WHERE id = %s",
                    (case_id,),
                )
                row = cursor.fetchone()
        return row is not None and str(row[0]) in _OPEN_CASE_STATUSES

    def _within_business_hours(self, now: datetime) -> bool:
        return is_within_business_hours(
            now,
            timezone_name=self.settings.support_console_timezone,
            start=self.settings.support_business_hours_start,
            end=self.settings.support_business_hours_end,
            days=self.settings.support_business_days,
        )

    def _thin_bot_text(self, *, first_contact: bool, within_hours: bool) -> str:
        text = _ACK_TEXT_TEMPLATE if first_contact else ""
        if not within_hours:
            text = (text + _OUT_OF_HOURS_SUFFIX).format(
                days_label=_business_days_label(self.settings.support_business_days),
                start=self.settings.support_business_hours_start,
                end=self.settings.support_business_hours_end,
                timezone=self.settings.support_console_timezone,
            )
        return text.strip() or _ACK_TEXT_TEMPLATE

    def _append_message(
        self,
        *,
        case_id: str,
        role: str,
        content: str,
        actor_kind: str,
        actor_staff_id: str | None = None,
    ) -> str | None:
        sanitized = sanitize_for_persistence(content)
        if sanitized is None:
            return None
        with self.database_runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT conversation_id, status FROM support_cases WHERE id = %s
                    """,
                    (case_id,),
                )
                row = cursor.fetchone()
                if row is None or row[0] is None:
                    return None
                conversation_id, case_status = row[0], str(row[1])
                cursor.execute(
                    """
                    UPDATE conversations
                    SET status = 'human_active', updated_at = now(), last_message_at = now()
                    WHERE id = %s AND status = ANY(%s)
                    """,
                    (conversation_id, list(_HUMAN_TAKEOVER_STATUSES)),
                )
                message_id = append_case_message(
                    cursor,
                    conversation_id=conversation_id,
                    role=role,
                    content=sanitized,
                )
                cursor.execute(
                    """
                    INSERT INTO support_case_events (
                      case_id, actor_staff_id, actor_kind, actor_customer_id,
                      action, from_status, to_status
                    )
                    VALUES (%s, %s, %s, NULL, 'message', %s, %s)
                    """,
                    (case_id, actor_staff_id, actor_kind, case_status, case_status),
                )
        return message_id


def append_case_message(
    cursor: Any,
    *,
    conversation_id: Any,
    role: str,
    content: str,
) -> str:
    """Append a single ad-hoc message to an existing conversation.

    Deliberately NOT ``ConversationRepository.append_turn``: that helper is
    coupled to the RAG audit-turn model (paired user+assistant rows sharing
    one ``turn_id``, FK'd to ``chat_audits``). A WhatsApp-bridge message is a
    single, ad-hoc row outside that model -- its own fresh ``turn_id`` keeps
    it clear of ``idx_messages_turn_role``, and ``chat_audit_id`` stays NULL
    (nullable by design, see migration 006).
    """

    turn_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO messages (
          conversation_id, turn_id, request_id, channel, chat_audit_id,
          role, content, escalated, handoff_reasons, message_references,
          error_code, redaction_version, delivery_status
        )
        VALUES (%s, %s, NULL, 'whatsapp_support', NULL, %s, %s, false,
                '[]'::jsonb, '[]'::jsonb, NULL, %s, %s)
        RETURNING id
        """,
        (
            conversation_id,
            turn_id,
            role,
            content,
            REDACTION_VERSION,
            "queued" if role == "agent" else None,
        ),
    )
    return str(cursor.fetchone()[0])


_STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}


def apply_delivery_status(database_runtime: DatabaseRuntime, status: MetaMessageStatus) -> bool:
    """Update a previously-sent agent message's delivery status.

    Monotonic by rank so a late/out-of-order 'sent' callback never overwrites
    a more advanced 'delivered'/'read' state; 'failed' always wins (a failure
    can happen at any point). Returns False when the message_id is unknown
    (message not tracked, or belongs to a different flow).
    """

    new_rank = _STATUS_RANK.get(status.status)
    if new_rank is None:
        return False
    with database_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT delivery_status FROM messages WHERE meta_message_id = %s",
                (status.message_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            current_rank = _STATUS_RANK.get(row[0], -1)
            if status.status != "failed" and new_rank <= current_rank:
                return False
            cursor.execute(
                "UPDATE messages SET delivery_status = %s WHERE meta_message_id = %s",
                (status.status, status.message_id),
            )
    return True


_DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def is_within_business_hours(
    now: datetime,
    *,
    timezone_name: str,
    start: str,
    end: str,
    days: str,
) -> bool:
    local = now.astimezone(ZoneInfo(timezone_name))
    allowed_days = {day.strip().lower() for day in days.split(",") if day.strip()}
    if _DAY_ORDER[local.weekday()] not in allowed_days:
        return False
    start_h, start_m = _parse_hhmm(start)
    end_h, end_m = _parse_hhmm(end)
    minutes_now = local.hour * 60 + local.minute
    return (start_h * 60 + start_m) <= minutes_now < (end_h * 60 + end_m)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, _, minute_str = value.strip().partition(":")
    return int(hour_str), int(minute_str or "0")


def _business_days_label(days: str) -> str:
    values = [day.strip().lower() for day in days.split(",") if day.strip()]
    labels = {
        "mon": "seg", "tue": "ter", "wed": "qua", "thu": "qui",
        "fri": "sex", "sat": "sab", "sun": "dom",
    }
    if values == ["mon", "tue", "wed", "thu", "fri"]:
        return "segunda a sexta"
    return ", ".join(labels.get(day, day) for day in values)


def _extract_token(text: str) -> str | None:
    match = _TOKEN_PATTERN.search(text)
    return match.group(0) if match else None
