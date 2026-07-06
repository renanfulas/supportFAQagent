"""Render customer-facing status notifications for a support case transition
(Fase 2 da ponte WhatsApp<->console).

Pure functions only: no DB, no I/O, no secrets -- mirrors the pattern of
``app/notifications/support_team.py``. The write path
(``app/support/transitions.py``) calls these inside the SAME transaction that
records the status transition, enqueuing one WhatsApp event (free-form
inside the 24h window, template outside it -- the caller decides which by
passing ``window_open``) plus one paired e-mail event when the customer has
an e-mail on file and has not opted out.

Only two transitions are customer-facing here: ``-> in_progress`` (an agent
picked up the case) and ``-> closed`` (resolved, with a short summary). Any
other ``to_status`` (open, waiting_customer, cancelled) returns ``None`` --
no notification for those in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass


MAX_SUMMARY_CHARS = 400

_WHATSAPP_TEMPLATE_LABEL = {
    "in_progress": "atendente_assumiu",
    "closed": "ticket_resolvido",
}


@dataclass(frozen=True)
class CustomerWhatsAppNotification:
    """``kind='template'`` carries the internal label (resolved to the WABA
    name by the caller, e.g. via ``resolve_template_name``), not the raw
    Meta template name -- this module knows nothing about WABA config."""

    kind: str  # "freeform" | "template"
    idempotency_key: str
    text: str | None = None
    template_label: str | None = None


@dataclass(frozen=True)
class CustomerEmailNotification:
    to: str
    subject: str
    body: str
    idempotency_key: str


def render_customer_status_whatsapp(
    *,
    case_id: str,
    to_status: str,
    window_open: bool,
    summary: str | None = None,
) -> CustomerWhatsAppNotification | None:
    text = _status_text(to_status, summary=summary)
    if text is None:
        return None
    idempotency_key = f"notify_customer_wa:{case_id}:{to_status}"
    if window_open:
        return CustomerWhatsAppNotification(
            kind="freeform", idempotency_key=idempotency_key, text=text
        )
    label = _WHATSAPP_TEMPLATE_LABEL[to_status]
    return CustomerWhatsAppNotification(
        kind="template", idempotency_key=idempotency_key, template_label=label
    )


def render_customer_status_email(
    *,
    case_id: str,
    to_status: str,
    customer_email: str | None,
    opted_in: bool,
    summary: str | None = None,
) -> CustomerEmailNotification | None:
    """None when there is nothing to send: no e-mail on file, opted out, or
    ``to_status`` has no customer-facing message. Kept as a separate,
    parallel channel from WhatsApp -- the two never share an idempotency key
    or a delivery guarantee."""

    if not customer_email or not opted_in:
        return None
    body = _status_text(to_status, summary=summary)
    if body is None:
        return None
    subject = _EMAIL_SUBJECT.get(to_status)
    if subject is None:
        return None
    idempotency_key = f"notify_customer_email:{case_id}:{to_status}"
    return CustomerEmailNotification(
        to=customer_email, subject=subject, body=body, idempotency_key=idempotency_key
    )


_EMAIL_SUBJECT = {
    "in_progress": "Atualizacao do seu chamado",
    "closed": "Seu chamado foi resolvido",
}


def _status_text(to_status: str, *, summary: str | None) -> str | None:
    if to_status == "in_progress":
        return "Um atendente assumiu seu chamado e vai te responder por aqui."
    if to_status == "closed":
        trimmed = (summary or "").strip()[:MAX_SUMMARY_CHARS]
        base = "Seu chamado foi resolvido."
        return f"{base} Resumo: {trimmed}" if trimmed else base
    return None
