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

from dataclasses import dataclass
from typing import Any

from app.core.errors import TransactionBusinessError
from app.core.persistence_sanitize import sanitize_for_persistence
from app.db.runtime import DatabaseRuntime


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
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

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

        return TransitionResult(
            case_id=case_id,
            from_status=current_status,
            to_status=to_status,
            assignee_staff_id=new_assignee,
            assignee_display_name=assignee_display_name,
        )


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    trimmed = note.strip()
    if not trimmed:
        return None
    return sanitize_for_persistence(trimmed[:NOTE_MAX_LENGTH])
