"""Ponte WhatsApp<->console: token do deep link e binding cifrado do wa_id.

Duas primitivas de seguranca distintas, com secrets dedicados (nunca reusar
``identity_hash_secret``, que e HMAC/hash, nao cifra reversivel):

- **Token do caso** (``mint_case_token``/``resolve_case_token``): auto-
  verificavel via HMAC sobre o ``case_id``, sem storage. E o mecanismo
  PRIMARIO de vinculo cliente<->caso no deep link -- nao o ``phone_hash``,
  porque um caso native-origin (WhatsApp) provavelmente nao tem
  ``customer_id`` (a frente de identidade decidiu que o WhatsApp nativo se
  apoia em hash de sessao, nao em Auth).
- **Binding cifrado** (``CaseWhatsAppBindingRepository``): o ``wa_id``
  (E.164) do cliente, cifrado em repouso (Fernet/AES-GCM), escopado a um
  unico caso, com retencao dupla -- purgado no fechamento/cancelamento do
  caso OU apos ``SUPPORT_WA_BINDING_MAX_DAYS`` (default 15 dias) sem
  resolucao, o que vier primeiro.

Ver docs/quality-plans/whatsapp-support-bridge-tech-plan.md ("Fronteira De
Privacidade" e "Vinculo De Identidade").
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app.db.runtime import DatabaseRuntime


TOKEN_PREFIX = "case"


class WaBindingConfigurationError(RuntimeError):
    """SUPPORT_WA_ENC_KEY or SUPPORT_WA_TOKEN_SECRET is not configured."""


def mint_case_token(case_id: str, *, secret: str) -> str:
    """Build a self-verifying, opaque deep-link token for ``case_id``.

    No storage needed: the token carries the case id plus an HMAC signature,
    so a party without ``secret`` cannot forge a token for an arbitrary
    (unguessable, UUID) case id.
    """

    if not secret:
        raise WaBindingConfigurationError("SUPPORT_WA_TOKEN_SECRET is required")
    signature = _sign(case_id, secret=secret)
    return f"{TOKEN_PREFIX}.{case_id}.{signature}"


def resolve_case_token(token: str, *, secret: str) -> str | None:
    """Verify a deep-link token and return the case id, or ``None`` if invalid.

    Never raises on malformed input -- an invalid/absent token must fall
    through to a friendly error, never a crash or a wrong-case bind.
    """

    if not secret or not token:
        return None
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    _, case_id, signature = parts
    expected = _sign(case_id, secret=secret)
    if not hmac.compare_digest(expected, signature):
        return None
    return case_id


def _sign(case_id: str, *, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), case_id.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")


def build_support_deep_link(
    case_id: str,
    *,
    support_phone_e164: str,
    token_secret: str,
) -> str:
    """``wa.me`` link that hands a customer off to the support number.

    Pre-fills the case token in the message text, so the customer's first
    inbound on the support number self-identifies the case (see
    ``resolve_case_token`` / ``SupportWhatsAppBridgeService._resolve_case_id``).
    Uses the support line's dialable E.164 number -- NOT
    ``META_SUPPORT_PHONE_NUMBER_ID``, which is Meta's internal API identifier
    and not something a customer can dial or link to.
    """

    token = mint_case_token(case_id, secret=token_secret)
    digits = "".join(char for char in support_phone_e164 if char.isdigit())
    prefill = urllib.parse.quote(f"Atendimento: {token}")
    return f"https://wa.me/{digits}?text={prefill}"


def _fernet(key: str) -> Fernet:
    if not key:
        raise WaBindingConfigurationError("SUPPORT_WA_ENC_KEY is required")
    # Derives a valid 32-byte urlsafe-base64 Fernet key from any operator-
    # provided secret string, so the env var stays a plain secret like the
    # project's other keys (identity_hash_secret, otp_digest_secret).
    derived = hashlib.sha256(f"{key}|encrypt".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_wa_id(wa_id: str, *, key: str) -> bytes:
    return _fernet(key).encrypt(wa_id.encode("utf-8"))


def decrypt_wa_id(token: bytes, *, key: str) -> str | None:
    try:
        return _fernet(key).decrypt(bytes(token)).decode("utf-8")
    except InvalidToken:
        return None


def hash_wa_id(wa_id: str, *, key: str) -> str:
    """Deterministic lookup hash for a wa_id, keyed off the SAME operator
    secret as the cipher but domain-separated ("|hash" vs "|encrypt") so the
    two derived sub-keys never collide. Fernet output is non-deterministic
    (random IV), so ``wa_id_encrypted`` cannot be searched by equality --
    this hash is what lets a repeat inbound message find its open case
    without decrypting every live binding."""

    if not key:
        raise WaBindingConfigurationError("SUPPORT_WA_ENC_KEY is required")
    digest = hmac.new(
        f"{key}|hash".encode("utf-8"), wa_id.encode("utf-8"), hashlib.sha256
    )
    return digest.hexdigest()


@dataclass(frozen=True)
class CaseWhatsAppBinding:
    case_id: str
    wa_id: str
    last_customer_message_at: datetime | None
    bound_at: datetime
    expires_at: datetime


class CaseWhatsAppBindingRepository:
    """PostgreSQL adapter for ``case_whatsapp_bindings`` (migration 016)."""

    def __init__(self, runtime: DatabaseRuntime, *, enc_key: str) -> None:
        self.runtime = runtime
        self.enc_key = enc_key

    def bind(
        self,
        *,
        case_id: str,
        wa_id: str,
        max_days: int,
        now: datetime | None = None,
    ) -> None:
        """Create or re-create the binding for a case.

        Idempotent: a repeated bind (e.g., the customer's first message
        arriving twice) just refreshes the encrypted wa_id and the window.
        Re-binding after a purge (``unbound_at`` set) resets the retention
        clock from ``now``.
        """

        moment = now or datetime.now(UTC)
        expires_at = moment + timedelta(days=max_days)
        encrypted = encrypt_wa_id(wa_id, key=self.enc_key)
        wa_hash = hash_wa_id(wa_id, key=self.enc_key)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO case_whatsapp_bindings (
                      case_id, wa_id_encrypted, wa_id_hash,
                      last_customer_message_at, bound_at, expires_at, unbound_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NULL)
                    ON CONFLICT (case_id) DO UPDATE SET
                      wa_id_encrypted = EXCLUDED.wa_id_encrypted,
                      wa_id_hash = EXCLUDED.wa_id_hash,
                      last_customer_message_at = EXCLUDED.last_customer_message_at,
                      bound_at = EXCLUDED.bound_at,
                      expires_at = EXCLUDED.expires_at,
                      unbound_at = NULL
                    """,
                    (case_id, encrypted, wa_hash, moment, moment, expires_at),
                )

    def find_open_case_id_by_wa_id(self, wa_id: str) -> str | None:
        """Resolve a repeat inbound message to its open case by wa_id hash.

        Only the FIRST message from a customer needs the deep-link token;
        follow-ups on an already-bound case are found this way instead.

        Known Fase 1 limitation: if the same customer has two simultaneously
        open WhatsApp-bound cases, this returns the most recently bound one
        (deterministic, but not necessarily "the one they mean"). Rare in
        practice (one escalation -> one case); revisit if it becomes real.
        """

        wa_hash = hash_wa_id(wa_id, key=self.enc_key)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT case_id FROM case_whatsapp_bindings
                    WHERE wa_id_hash = %s AND unbound_at IS NULL
                    ORDER BY bound_at DESC
                    LIMIT 1
                    """,
                    (wa_hash,),
                )
                row = cursor.fetchone()
        return str(row[0]) if row is not None else None

    def touch_customer_message(
        self,
        *,
        case_id: str,
        now: datetime | None = None,
    ) -> None:
        """Reopen the 24h Meta window: a new inbound message from the customer."""

        moment = now or datetime.now(UTC)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE case_whatsapp_bindings
                    SET last_customer_message_at = %s
                    WHERE case_id = %s AND unbound_at IS NULL
                    """,
                    (moment, case_id),
                )

    def get(self, case_id: str) -> CaseWhatsAppBinding | None:
        """Live (non-purged) binding for a case, wa_id decrypted."""

        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT wa_id_encrypted, last_customer_message_at,
                           bound_at, expires_at
                    FROM case_whatsapp_bindings
                    WHERE case_id = %s AND unbound_at IS NULL
                    """,
                    (case_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        wa_id = decrypt_wa_id(row[0], key=self.enc_key)
        if wa_id is None:
            return None
        return CaseWhatsAppBinding(
            case_id=case_id,
            wa_id=wa_id,
            last_customer_message_at=row[1],
            bound_at=row[2],
            expires_at=row[3],
        )

    def is_window_open(
        self,
        binding: CaseWhatsAppBinding,
        *,
        window_hours: int,
        now: datetime | None = None,
    ) -> bool:
        """Best-effort mirror of the Meta 24h customer-service window.

        Authoritative on Meta's side, not here -- a free-form send can still
        be rejected even when this returns True (see the dispatcher's
        fallback to a template on rejection).
        """

        if binding.last_customer_message_at is None:
            return False
        moment = now or datetime.now(UTC)
        return moment - binding.last_customer_message_at < timedelta(hours=window_hours)

    def unbind_on_close(self, case_id: str, *, now: datetime | None = None) -> None:
        """Purge immediately when the case closes/cancels (retention: close)."""

        moment = now or datetime.now(UTC)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE case_whatsapp_bindings
                    SET wa_id_encrypted = '\\x'::bytea, unbound_at = %s
                    WHERE case_id = %s AND unbound_at IS NULL
                    """,
                    (moment, case_id),
                )

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Purge bindings past their retention teto (15d without resolution).

        Meant to run opportunistically (mirrors ``staff_login_hints`` pruning
        on the OTP start path) or from a small periodic script/cron.
        Returns the number of bindings purged.
        """

        moment = now or datetime.now(UTC)
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE case_whatsapp_bindings
                    SET wa_id_encrypted = '\\x'::bytea, unbound_at = %s
                    WHERE unbound_at IS NULL AND expires_at <= %s
                    """,
                    (moment, moment),
                )
                return cursor.rowcount
