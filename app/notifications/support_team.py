"""Render support-team WhatsApp alerts from a durable support case.

Pure functions only: no DB, no I/O, no secrets. The write path
(``app/db/operational.py``) calls :func:`render_support_team_notifications`
inside the same transaction that creates the ``support_case``, enqueuing one
``whatsapp.message.requested`` outbox event per internal recipient. The
dispatcher delivers them through the existing ``whatsapp_message`` route, so the
team is alerted with the same bounded handoff context the read inbox serves.

Privacy:

- Inputs are already-sanitized snapshot fields (summary, domain, reasons,
  references). Nothing here re-derives PII or logs raw values.
- Recipient numbers are internal team contacts from config and are kept verbatim
  on purpose, because the dispatcher needs them to deliver the message. They must
  therefore bypass ``sanitize_payload`` (which redacts phone-shaped strings) when
  the event is enqueued.
- The optional customer block (name/e-mail/phone last4) is only supplied by the
  LGPD consent path (``promote_pending_consent``): the customer proved the phone
  via OTP and explicitly authorized direct contact, and the e-mail was provided
  for exactly this use. It never comes from unverified chat input.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


MAX_SUMMARY_CHARS = 400
MAX_REFERENCES = 5


@dataclass(frozen=True)
class SupportTeamNotification:
    """A single rendered alert addressed to one internal recipient."""

    to: str
    text: str
    idempotency_key: str


def render_support_team_notifications(
    *,
    turn_id: str,
    support_case_id: str,
    domain: str,
    handoff_reasons: list[str],
    summary: str | None,
    references: list[str],
    recipients: list[str],
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_phone_last4: str | None = None,
) -> list[SupportTeamNotification]:
    """Build one notification per distinct recipient for a handoff turn.

    The idempotency key is stable for a given ``turn_id`` + recipient, so a retry
    of the same escalated turn never produces a duplicate alert per recipient.
    Returns an empty list when there are no usable recipients. The customer
    fields are only passed on the consent path (see module privacy note).
    """

    clean_recipients = _dedupe_recipients(recipients)
    if not clean_recipients:
        return []
    text = _build_alert_text(
        support_case_id=support_case_id,
        domain=domain,
        handoff_reasons=handoff_reasons,
        summary=summary,
        references=references,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone_last4=customer_phone_last4,
    )
    return [
        SupportTeamNotification(
            to=recipient,
            text=text,
            idempotency_key=_idempotency_key(turn_id, recipient),
        )
        for recipient in clean_recipients
    ]


def _dedupe_recipients(recipients: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in recipients:
        value = raw.strip()
        if value:
            seen.setdefault(value, None)
    return list(seen)


def _idempotency_key(turn_id: str, recipient: str) -> str:
    # Hash the recipient so the durable key never carries a raw phone number.
    token = hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:12]
    return f"support_notify:{turn_id}:{token}"


def _build_alert_text(
    *,
    support_case_id: str,
    domain: str,
    handoff_reasons: list[str],
    summary: str | None,
    references: list[str],
    customer_name: str | None = None,
    customer_email: str | None = None,
    customer_phone_last4: str | None = None,
) -> str:
    motivo = ", ".join(reason for reason in handoff_reasons if reason)
    lines = [
        "Novo atendimento humano",
        f"Caso: {support_case_id}",
        f"Dominio: {domain}",
        f"Motivo: {motivo or 'acao humana necessaria'}",
    ]
    name = (customer_name or "").strip()
    if name:
        lines.append(f"Cliente: {name}")
    email = (customer_email or "").strip()
    if email:
        lines.append(f"Contato autorizado (LGPD): {email}")
    last4 = (customer_phone_last4 or "").strip()
    if last4:
        lines.append(f"WhatsApp verificado: final {last4}")
    if summary:
        trimmed = summary.strip()[:MAX_SUMMARY_CHARS]
        if trimmed:
            lines.append(f"Resumo: {trimmed}")
    refs = [reference for reference in references if reference][:MAX_REFERENCES]
    if refs:
        lines.append(f"Referencias: {', '.join(refs)}")
    return "\n".join(lines)
