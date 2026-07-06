"""Fase B: transicoes auditadas de ``support_cases`` (dono na fila).

Compare-and-swap no mesmo padrao do consent gate
(``app/db/operational.py:promote_pending_consent``): ``SELECT ... FOR UPDATE``
trava a linha e le o estado atual dentro da transacao; o ``UPDATE`` seguinte
usa o status atual como guarda extra (redundante com o lock em uso normal,
mas barato e documentado no plano como defesa em profundidade). O evento
auditavel e inserido **na mesma transacao** do ``UPDATE`` — commit e rollback
sempre em conjunto.

Decisao v1: ``claim`` exige caso sem dono; as demais acoes qualquer staff
ativo pode executar (time pequeno, tudo auditado).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import TransactionBusinessError
from app.core.persistence_sanitize import sanitize_for_persistence
from app.db.runtime import DatabaseRuntime
from app.notifications.customer_status import (
    render_customer_status_email,
    render_customer_status_whatsapp,
)
from app.support.customer_preferences import email_notifications_opted_in
from app.support.wa_binding import decrypt_wa_id
from app.support.whatsapp_bridge import resolve_template_name


NOTE_MAX_LENGTH = 500

VALID_ACTIONS = {
    "claim",
    "release",
    "wait_customer",
    "resume",
    "close",
    "cancel",
}

# (from_status, action) -> to_status
TRANSITION_MATRIX: dict[tuple[str, str], str] = {
    ("open", "claim"): "in_progress",
    ("in_progress", "release"): "open",
    ("in_progress", "wait_customer"): "waiting_customer",
    ("waiting_customer", "resume"): "in_progress",
    ("in_progress", "close"): "closed",
    ("open", "cancel"): "cancelled",
    ("in_progress", "cancel"): "cancelled",
    # Valvula de escape para o ticket que nasceu 'pending_consent' e cujo
    # cliente nunca confirmou o consentimento LGPD: sem isso ele ficaria
    # eterno na fila (visivel so com filtro explicito, sem acao possivel).
    # Cancelar nao notifica ninguem — so encerra o caso abandonado.
    ("pending_consent", "cancel"): "cancelled",
}
CLOSING_STATUSES = {"closed", "cancelled"}


class CaseNotFound(TransactionBusinessError):
    pass


class InvalidTransition(TransactionBusinessError):
    """Acao nao aplicavel ao status atual, ou CAS perdido (defesa em profundidade).

    Both are raised from inside ``with self.runtime.transaction()`` below, so
    they must subclass TransactionBusinessError to survive that wrapper
    unchanged instead of being reported as DatabaseUnavailableError (503).
    """

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"invalid transition from status={status}")


@dataclass(frozen=True)
class TransitionResult:
    case_id: str
    from_status: str
    to_status: str
    assignee_staff_id: str | None
    assignee_display_name: str | None


class SupportCaseTransitionService:
    def __init__(
        self,
        runtime: DatabaseRuntime,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self._now = now or (lambda: datetime.now(UTC))

    def apply(
        self,
        *,
        case_id: str,
        action: str,
        actor_staff_id: str,
        note: str | None,
    ) -> TransitionResult:
        if action not in VALID_ACTIONS:
            raise ValueError(f"unknown transition action: {action}")
        clean_note = _clean_note(note)

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, assignee_staff_id
                    FROM support_cases
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (case_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise CaseNotFound(case_id)
                current_status = str(row[0])
                current_assignee = str(row[1]) if row[1] else None

                to_status = TRANSITION_MATRIX.get((current_status, action))
                if to_status is None:
                    raise InvalidTransition(current_status)
                if action == "claim" and current_assignee is not None:
                    raise InvalidTransition(current_status)

                if action == "claim":
                    new_assignee: str | None = actor_staff_id
                elif action == "release":
                    new_assignee = None
                else:
                    new_assignee = current_assignee

                if action == "claim":
                    cursor.execute(
                        """
                        UPDATE support_cases
                        SET status = %s, assignee_staff_id = %s, updated_at = now()
                        WHERE id = %s AND status = 'open' AND assignee_staff_id IS NULL
                        """,
                        (to_status, new_assignee, case_id),
                    )
                elif action == "release":
                    cursor.execute(
                        """
                        UPDATE support_cases
                        SET status = %s, assignee_staff_id = NULL, updated_at = now()
                        WHERE id = %s AND status = %s
                        """,
                        (to_status, case_id, current_status),
                    )
                elif to_status in CLOSING_STATUSES:
                    cursor.execute(
                        """
                        UPDATE support_cases
                        SET status = %s, updated_at = now(), closed_at = now()
                        WHERE id = %s AND status = %s
                        """,
                        (to_status, case_id, current_status),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE support_cases
                        SET status = %s, updated_at = now()
                        WHERE id = %s AND status = %s
                        """,
                        (to_status, case_id, current_status),
                    )
                if cursor.rowcount == 0:
                    # O SELECT ... FOR UPDATE ja serializa o acesso; isto so
                    # dispararia se outra transacao commitasse entre a leitura e
                    # a escrita desta mesma transacao (nao deveria acontecer).
                    # Guard de defesa em profundidade, igual ao consent gate.
                    raise InvalidTransition(current_status)

                cursor.execute(
                    """
                    INSERT INTO support_case_events (
                      case_id, actor_staff_id, action, from_status, to_status,
                      note_sanitized
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        case_id,
                        actor_staff_id,
                        action,
                        current_status,
                        to_status,
                        clean_note,
                    ),
                )

                assignee_display_name = None
                if new_assignee is not None:
                    cursor.execute(
                        "SELECT display_name FROM staff_members WHERE id = %s",
                        (new_assignee,),
                    )
                    display_row = cursor.fetchone()
                    assignee_display_name = str(display_row[0]) if display_row else None

                self._maybe_notify_customer(
                    cursor, case_id=case_id, action=action, to_status=to_status
                )

        return TransitionResult(
            case_id=case_id,
            from_status=current_status,
            to_status=to_status,
            assignee_staff_id=new_assignee,
            assignee_display_name=assignee_display_name,
        )

    def _maybe_notify_customer(
        self, cursor: Any, *, case_id: str, action: str, to_status: str
    ) -> None:
        """Fase 2: proactive customer-facing notification, same transaction
        as the transition. Only two triggers matter here: ``claim`` landing
        the case in ``in_progress`` (an agent just picked it up -- ``resume``
        also reaches ``in_progress`` but the customer already knows someone's
        on it, so that path stays silent), and any action landing in
        ``closed`` (only ``close`` reaches it per ``TRANSITION_MATRIX``).
        Checked first, before any query, so the common actions (release,
        wait_customer, resume, cancel) never pay for the lookups below.
        """

        notifiable = (action == "claim" and to_status == "in_progress") or (
            to_status == "closed"
        )
        if not notifiable:
            return
        settings = self.runtime.settings

        cursor.execute(
            """
            SELECT sc.customer_id, sc.context_snapshot_sanitized, c.email
            FROM support_cases sc
            LEFT JOIN customers c ON c.id = sc.customer_id
            WHERE sc.id = %s
            """,
            (case_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return
        customer_id, snapshot_raw, customer_email = row

        summary = None
        if to_status == "closed":
            snapshot = _load_json(snapshot_raw, default={})
            if isinstance(snapshot, dict):
                summary = snapshot.get("summary")

        wa_id, window_open = self._resolve_wa_window(cursor, case_id=case_id, settings=settings)

        if wa_id is not None:
            notification = render_customer_status_whatsapp(
                case_id=case_id,
                to_status=to_status,
                window_open=window_open,
                summary=summary,
            )
            if notification is not None:
                self._enqueue_customer_whatsapp(
                    cursor,
                    to=wa_id,
                    notification=notification,
                    case_id=case_id,
                    settings=settings,
                )

        if customer_id is not None and customer_email:
            opted_in = email_notifications_opted_in(cursor, str(customer_id))
            email_notification = render_customer_status_email(
                case_id=case_id,
                to_status=to_status,
                customer_email=customer_email,
                opted_in=opted_in,
                summary=summary,
            )
            if email_notification is not None:
                self._enqueue_customer_email(
                    cursor, notification=email_notification, case_id=case_id
                )

    def _resolve_wa_window(
        self, cursor: Any, *, case_id: str, settings: Any
    ) -> tuple[str | None, bool]:
        enc_key = getattr(settings, "support_wa_enc_key", None)
        if not enc_key:
            return None, False
        cursor.execute(
            """
            SELECT wa_id_encrypted, last_customer_message_at
            FROM case_whatsapp_bindings
            WHERE case_id = %s AND unbound_at IS NULL
            """,
            (case_id,),
        )
        binding_row = cursor.fetchone()
        if binding_row is None:
            return None, False
        wa_id = decrypt_wa_id(binding_row[0], key=enc_key)
        if wa_id is None:
            return None, False
        last_customer_message_at = binding_row[1]
        if last_customer_message_at is None:
            return wa_id, False
        window_hours = getattr(settings, "support_wa_window_hours", 24)
        window_open = (self._now() - last_customer_message_at) < timedelta(
            hours=window_hours
        )
        return wa_id, window_open

    def _enqueue_customer_whatsapp(
        self, cursor: Any, *, to: str, notification: Any, case_id: str, settings: Any
    ) -> None:
        if notification.kind == "freeform":
            event_type = "whatsapp.message.requested"
            payload = {
                "to": to,
                "text": notification.text,
                "support_case_id": case_id,
                "phone_number_kind": "support",
            }
        else:
            event_type = "whatsapp.template.requested"
            payload = {
                "to": to,
                "template_name": resolve_template_name(
                    notification.template_label, settings=settings
                ),
                "language_code": settings.support_wa_template_language,
                "support_case_id": case_id,
                "phone_number_kind": "support",
            }
        cursor.execute(
            """
            INSERT INTO operational_outbox (
              event_type, idempotency_key, request_id, payload_sanitized
            )
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (event_type, notification.idempotency_key, case_id, json.dumps(payload)),
        )

    def _enqueue_customer_email(
        self, cursor: Any, *, notification: Any, case_id: str
    ) -> None:
        payload = {
            "to": notification.to,
            "subject": notification.subject,
            "body": notification.body,
            "support_case_id": case_id,
        }
        cursor.execute(
            """
            INSERT INTO operational_outbox (
              event_type, idempotency_key, request_id, payload_sanitized
            )
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                "email.message.requested",
                notification.idempotency_key,
                case_id,
                json.dumps(payload),
            ),
        )


def _load_json(value: Any, *, default: Any) -> Any:
    """JSONB columns may arrive parsed (psycopg default) or as text."""

    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    trimmed = note.strip()
    if not trimmed:
        return None
    return sanitize_for_persistence(trimmed[:NOTE_MAX_LENGTH])
