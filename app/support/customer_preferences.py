"""Leitura do opt-out de notificacao por e-mail (Fase 2 da ponte
WhatsApp<->console).

``customer_preferences`` (migration 009) ainda nao tem nenhum leitor/escritor
no projeto; este e o primeiro uso real. So a linha GLOBAL (``domain_id IS
NULL``) e lida -- a preferencia de notificacao de status nao e especifica de
dominio.

Default e OPT-IN: o consentimento LGPD (Sprint 4b) ja cobre "contato direto
da equipe" e o e-mail foi dado explicitamente para esse fim, entao a ausencia
de preferencia (ou de qualquer linha) significa notificar. So um valor
explicito ``false`` desliga.
"""

from __future__ import annotations

import json
from typing import Any


EMAIL_NOTIFICATIONS_KEY = "notify_status_by_email"


def email_notifications_opted_in(cursor: Any, customer_id: str) -> bool:
    cursor.execute(
        """
        SELECT preferences_json
        FROM customer_preferences
        WHERE customer_id = %s AND domain_id IS NULL
        """,
        (customer_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return True
    preferences = _load_json(row[0], default={})
    if not isinstance(preferences, dict):
        return True
    value = preferences.get(EMAIL_NOTIFICATIONS_KEY, True)
    return bool(value)


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
