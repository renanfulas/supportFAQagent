"""Fase 3 (opcional) da ponte WhatsApp<->console: unificacao de identidade
via OTP web -- Opcao B, opt-in (decisao registrada em
docs/quality-plans/whatsapp-support-bridge-tech-plan.md).

O WhatsApp nativo (Hermes/Meta) continua pseudonimo por padrao: nada aqui
roda automaticamente a cada mensagem recebida no numero bot. O historico so
se une quando o PROPRIO cliente prova posse do telefone via OTP no site --
mesmo gesto que ja existe hoje para o consent gate (Sprint 4b).

Nenhum hash/segredo existente e re-chaveado. ``verified_identities.phone_hash``
(dominio web, IDENTITY_HASH_SECRET), ``conversations.session_hash`` (dominio
nativo, PERSISTENCE_HASH_SECRET) e ``case_whatsapp_bindings.wa_id_hash``
(SUPPORT_WA_ENC_KEY) sao tres segredos diferentes por construcao deliberada
e nenhum e derivavel dos outros -- ver a secao "Fase 3" do tech-plan. O que
este modulo faz e RECALCULAR, a partir do telefone em claro (disponivel
apenas em ``WebWhatsAppAuthService.start()``, antes de ser descartado), o
mesmo ``session_hash`` de dominio nativo que
``app/integrations/hermes/chat_transport.py``/
``app/integrations/meta_whatsapp/chat_transport.py`` ja teriam gravado para
esse telefone -- e usa esse valor recalculado so para um JOIN por igualdade,
nunca para decifrar ou reverter nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.conversations.service import hash_session
from app.core.privacy import hash_sensitive_value


@dataclass(frozen=True)
class NativeSessionHashes:
    hermes: str
    meta: str


def compute_native_session_hashes(
    phone_e164: str, *, persistence_hash_secret: str
) -> NativeSessionHashes:
    """Recalcula os `conversations.session_hash` que o WhatsApp nativo teria
    gravado para este telefone -- mesma formula de
    ``_safe_hermes_session_id``/``_safe_meta_session_id`` (chat_transport)
    seguida de ``OperationalRepository._hash`` (hash_session), com o MESMO
    ``PERSISTENCE_HASH_SECRET`` usado na escrita original. Passar o secret
    explicitamente (nunca deixar `hash_sensitive_value` cair no fallback
    efemero) e o que garante que o recalculo bate com o valor gravado."""

    inner = hash_sensitive_value(phone_e164, secret=persistence_hash_secret)
    hermes_session_id = f"whatsapp:hermes:{inner}"
    meta_session_id = f"whatsapp:meta:{inner}"
    return NativeSessionHashes(
        hermes=hash_session(hermes_session_id, persistence_hash_secret),
        meta=hash_session(meta_session_id, persistence_hash_secret),
    )


@dataclass(frozen=True)
class NativeHistoryLinkResult:
    conversations_linked: int
    support_cases_linked: int


class NativeHistoryLinkRepository:
    """So preenche `customer_id` onde hoje esta NULL -- nunca sobrescreve um
    `customer_id` ja atribuido a outro cliente (mesma disciplina de
    `ConversationRepository._archive_identity_conflicts`: um valor existente
    e sinal de outra identidade, nao um dado a substituir)."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def link(
        self, *, customer_id: str, hashes: NativeSessionHashes
    ) -> NativeHistoryLinkResult:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversations
                    SET customer_id = %s, updated_at = now()
                    WHERE session_hash IN (%s, %s) AND customer_id IS NULL
                    """,
                    (customer_id, hashes.hermes, hashes.meta),
                )
                conversations_linked = cursor.rowcount
                cursor.execute(
                    """
                    UPDATE support_cases sc
                    SET customer_id = %s, updated_at = now()
                    FROM conversations c
                    WHERE sc.conversation_id = c.id
                      AND c.session_hash IN (%s, %s)
                      AND sc.customer_id IS NULL
                    """,
                    (customer_id, hashes.hermes, hashes.meta),
                )
                support_cases_linked = cursor.rowcount
        return NativeHistoryLinkResult(
            conversations_linked=conversations_linked,
            support_cases_linked=support_cases_linked,
        )
