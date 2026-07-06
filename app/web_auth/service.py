from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
import secrets
from threading import Lock
from uuid import uuid4

from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter
from app.identity.native_history_link import (
    NativeSessionHashes,
    compute_native_session_hashes,
)
from app.web_auth.delivery import OtpDeliveryAdapter, OtpDeliveryUnavailable
from app.web_auth.models import OtpChallenge, OtpDeliveryRequest, VerifiedIdentity
from app.web_auth.storage import WebAuthStore


E164_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class InvalidOrExpiredCode(Exception):
    pass


class ResendCooldown(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("resend cooldown active")


@dataclass(frozen=True)
class ConfirmedSession:
    identity: VerifiedIdentity
    # Fase 3 (opcional, opt-in): presente quando PERSISTENCE_HASH_SECRET
    # estava configurado no momento do start() deste desafio. O chamador
    # (rota) decide se/quando acionar o backfill do historico nativo -- este
    # servico so entrega os hashes recalculados, nunca escreve em
    # conversations/support_cases.
    native_session_hashes: NativeSessionHashes | None = None


class WebWhatsAppAuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: WebAuthStore,
        delivery: OtpDeliveryAdapter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.delivery = delivery
        self._now = now or (lambda: datetime.now(UTC))
        self._ip_limiter = InMemoryRateLimiter(
            max_requests=settings.otp_start_limit_per_ip_per_hour,
            window_seconds=60 * 60,
        )
        self._phone_limiter = InMemoryRateLimiter(
            max_requests=settings.otp_start_limit_per_phone_per_15_minutes,
            window_seconds=15 * 60,
        )
        self._challenge_lock = Lock()

    def start(self, *, phone: str, client_host: str) -> OtpChallenge:
        normalized_phone = normalize_phone(phone)
        phone_hash = self._digest_identity(normalized_phone)
        self._ip_limiter.check(client_host)
        self._phone_limiter.check(phone_hash)
        now = self._now()
        with self._challenge_lock:
            previous = self.store.latest_challenge_for_phone(phone_hash)
            if previous and previous.status == "pending":
                retry_at = previous.created_at + timedelta(
                    seconds=self.settings.otp_resend_cooldown_seconds,
                )
                if retry_at > now:
                    raise ResendCooldown(max(1, int((retry_at - now).total_seconds())))

            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge_id = str(uuid4())
            # Fase 3 (opcional, opt-in): unico momento em que o telefone bruto
            # existe em memoria -- nunca persistido em claro. Se
            # PERSISTENCE_HASH_SECRET nao estiver configurado, os hashes ficam
            # None e o backfill do WhatsApp nativo simplesmente nao acontece
            # para este desafio (degrada em silencio, nao bloqueia o OTP).
            native_hashes = self._native_session_hashes(normalized_phone)
            challenge = OtpChallenge(
                id=challenge_id,
                phone_hash=phone_hash,
                phone_last4=normalized_phone[-4:],
                code_digest=self._digest_code(challenge_id, code),
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.otp_code_ttl_seconds),
                attempts_remaining=self.settings.otp_max_attempts,
                native_session_hash_hermes=(
                    native_hashes.hermes if native_hashes else None
                ),
                native_session_hash_meta=(
                    native_hashes.meta if native_hashes else None
                ),
            )
            self.store.save_challenge(challenge)
        try:
            self.delivery.deliver(
                OtpDeliveryRequest(
                    challenge_id=challenge.id,
                    phone=normalized_phone,
                    code=code,
                    expires_in_seconds=self.settings.otp_code_ttl_seconds,
                ),
            )
        except OtpDeliveryUnavailable:
            challenge.status = "delivery_failed"
            self.store.save_challenge(challenge)
            raise
        return challenge

    def confirm(
        self,
        *,
        challenge_id: str,
        code: str,
        session_id: str,
    ) -> ConfirmedSession:
        challenge = self.store.consume_challenge(
            challenge_id,
            self._digest_code(challenge_id, code),
            self._now(),
        )
        if challenge is None:
            raise InvalidOrExpiredCode
        identity = self.store.get_identity_for_phone(challenge.phone_hash)
        if identity is None:
            identity = VerifiedIdentity(
                id=str(uuid4()),
                phone_hash=challenge.phone_hash,
                phone_last4=challenge.phone_last4,
                verified_at=self._now(),
            )
            identity = self.store.save_identity(identity)
        elif identity.customer_id is None:
            identity = self.store.save_identity(identity)
        self.store.bind_session(self._digest_identity(session_id), identity)
        native_hashes = None
        if challenge.native_session_hash_hermes and challenge.native_session_hash_meta:
            native_hashes = NativeSessionHashes(
                hermes=challenge.native_session_hash_hermes,
                meta=challenge.native_session_hash_meta,
            )
        return ConfirmedSession(identity=identity, native_session_hashes=native_hashes)

    def get_session_identity(self, session_id: str) -> VerifiedIdentity | None:
        return self.store.get_identity_for_session(self._digest_identity(session_id))

    def _native_session_hashes(self, phone_e164: str) -> NativeSessionHashes | None:
        if not getattr(self.settings, "enable_native_identity_link", False):
            return None
        secret = self.settings.persistence_hash_secret
        if not secret:
            return None
        return compute_native_session_hashes(phone_e164, persistence_hash_secret=secret)

    def logout(self, session_id: str) -> None:
        self.store.clear_session(self._digest_identity(session_id))

    def _digest_identity(self, value: str) -> str:
        return _hmac_digest(self.settings.identity_hash_secret or "", value)

    def _digest_code(self, challenge_id: str, code: str) -> str:
        return _hmac_digest(self.settings.otp_digest_secret or "", f"{challenge_id}:{code}")


def normalize_phone(phone: str) -> str:
    normalized = phone.strip()
    if not E164_PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("phone must use E.164 format")
    return normalized


def _hmac_digest(secret: str, value: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
