"""Autenticacao staff do console de suporte (OTP WhatsApp dedicado).

Staff nao e cliente: o confirm daqui escreve somente em ``staff_sessions`` e
``staff_login_hints`` (migration 014), nunca em ``customers`` ou
``verified_identities``. As primitivas de OTP (normalizacao E.164, HMAC,
desafio com expiracao/tentativas e o adapter de entrega WhatsApp) sao as
mesmas de ``app/web_auth/``.

Sessao diaria de verdade: ``expires_at`` e a proxima
``SUPPORT_STAFF_SESSION_EXPIRY_HOUR`` no fuso ``SUPPORT_CONSOLE_TIMEZONE``,
sem renovacao deslizante — todo dia comeca com login novo e a sessao nunca
morre no meio do expediente.

Lembrete de dispositivo (1 clique): o cookie carrega ``<token>.<E.164>``. O
banco guarda apenas o HMAC do token; o telefone bruto vive somente no cookie
HttpOnly do proprio operador e so e aceito se o seu HMAC bater com o
``phone_hash`` do staff dono do lembrete — adulterar o telefone quebra o
vinculo e o lembrete e ignorado. Sozinho, o lembrete nao autentica: apenas
dispara OTP para o WhatsApp registrado do operador.

Anti-enumeracao: telefone fora de ``staff_members`` recebe o mesmo resultado
com ``challenge_id`` sintetico (nunca persistido; o confirm dele cai no mesmo
``invalid_or_expired_code``), e o cooldown de reenvio e aplicado por limiter
uniforme — staff e nao-staff respondem identico.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter
from app.db.runtime import DatabaseRuntime
from app.web_auth.delivery import OtpDeliveryAdapter, OtpDeliveryUnavailable
from app.web_auth.models import OtpChallenge, OtpDeliveryRequest
from app.web_auth.service import InvalidOrExpiredCode, _hmac_digest, normalize_phone
from app.web_auth.storage import WebAuthStore


PHONE_HASH_LOG_PREFIX_LENGTH = 12


class StaffPhoneRequired(Exception):
    """Start without a typed phone and without a usable device hint."""


@dataclass(frozen=True)
class StaffMember:
    id: str
    phone_hash: str
    phone_last4: str
    display_name: str
    status: str = "active"


@dataclass(frozen=True)
class StaffPrincipal:
    staff_id: str
    display_name: str
    expires_at: datetime


@dataclass(frozen=True)
class StaffStartResult:
    challenge_id: str
    staff_match: bool
    delivery_failed: bool
    phone_hash_prefix: str


@dataclass(frozen=True)
class StaffLoginResult:
    principal: StaffPrincipal
    session_token: str
    hint_cookie_value: str | None


class StaffAuthStore(Protocol):
    def get_active_staff_by_phone_hash(self, phone_hash: str) -> StaffMember | None: ...
    def create_session(
        self,
        session_hash: str,
        staff_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...
    def get_session_principal(
        self,
        session_hash: str,
        now: datetime,
    ) -> StaffPrincipal | None: ...
    def delete_session(self, session_hash: str) -> None: ...
    def delete_expired_sessions(self, now: datetime) -> None: ...
    def save_hint(self, hint_hash: str, staff_id: str, now: datetime) -> None: ...
    def get_hint_staff(self, hint_hash: str, now: datetime) -> StaffMember | None: ...
    def delete_hint(self, hint_hash: str) -> None: ...
    def delete_expired_hints(self, cutoff: datetime) -> None: ...


def next_session_cutoff(now: datetime, timezone_name: str, hour: int) -> datetime:
    """Next occurrence of ``hour``:00 in the team timezone, strictly ahead."""

    team_zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(team_zone)
    cutoff = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if cutoff <= local_now:
        cutoff = cutoff + timedelta(days=1)
    return cutoff.astimezone(UTC)


def build_hint_cookie_value(opaque_token: str, phone: str) -> str:
    return f"{opaque_token}.{phone}"


def parse_hint_cookie_value(value: str | None) -> tuple[str, str] | None:
    """Split ``<token>.<E.164>``; the urlsafe token never contains a dot."""

    if not value:
        return None
    opaque_token, separator, phone = value.partition(".")
    if not separator or not opaque_token or not phone:
        return None
    return opaque_token, phone


class StaffConsoleAuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        staff_store: StaffAuthStore,
        challenge_store: WebAuthStore,
        delivery: OtpDeliveryAdapter,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.staff_store = staff_store
        self.challenge_store = challenge_store
        self.delivery = delivery
        self._now = now or (lambda: datetime.now(UTC))
        self._ip_limiter = InMemoryRateLimiter(
            max_requests=settings.support_otp_start_per_ip_per_hour,
            window_seconds=60 * 60,
        )
        self._phone_limiter = InMemoryRateLimiter(
            max_requests=settings.support_otp_start_per_phone_per_hour,
            window_seconds=60 * 60,
        )
        # Resend cooldown as a uniform limiter (instead of inspecting stored
        # challenges): a non-staff probe hits the exact same 429 a staff phone
        # would, so the cooldown never becomes an enumeration oracle.
        self._resend_limiter = InMemoryRateLimiter(
            max_requests=1,
            window_seconds=settings.otp_resend_cooldown_seconds,
        )

    def start(
        self,
        *,
        phone: str | None,
        hint_cookie: str | None,
        client_host: str,
    ) -> StaffStartResult:
        now = self._now()
        normalized_phone = self._resolve_hint_phone(hint_cookie, now)
        if normalized_phone is None:
            if not phone or not phone.strip():
                raise StaffPhoneRequired
            normalized_phone = normalize_phone(phone)
        phone_hash = self._digest_identity(normalized_phone)
        self._ip_limiter.check(client_host)
        self._phone_limiter.check(phone_hash)
        self._resend_limiter.check(phone_hash)
        self.staff_store.delete_expired_sessions(now)
        # Higiene: hints cujo cookie o operador ja descartou (limpou cookies,
        # trocou de maquina) nunca expiram no lado servidor — o TTL so vive no
        # cookie. Poda oportunista pelo mesmo TTL do cookie.
        self.staff_store.delete_expired_hints(
            now - timedelta(days=self.settings.support_staff_hint_ttl_days)
        )

        staff = self.staff_store.get_active_staff_by_phone_hash(phone_hash)
        if staff is None:
            # Synthetic challenge: random, never persisted, confirm fails with
            # the same invalid_or_expired_code. The response never says who is
            # staff.
            return StaffStartResult(
                challenge_id=str(uuid4()),
                staff_match=False,
                delivery_failed=False,
                phone_hash_prefix=phone_hash[:PHONE_HASH_LOG_PREFIX_LENGTH],
            )

        challenge, code = self._create_challenge(phone_hash, normalized_phone, now)
        delivery_failed = False
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
            # A resposta nao varia com a entrega: um 503 aqui denunciaria quem
            # e staff (o desafio sintetico nunca toca a entrega). O operador
            # simplesmente pede outro codigo.
            challenge.status = "delivery_failed"
            self.challenge_store.save_challenge(challenge)
            delivery_failed = True
        return StaffStartResult(
            challenge_id=challenge.id,
            staff_match=True,
            delivery_failed=delivery_failed,
            phone_hash_prefix=phone_hash[:PHONE_HASH_LOG_PREFIX_LENGTH],
        )

    def confirm(
        self,
        *,
        challenge_id: str,
        code: str,
        phone: str | None,
        hint_cookie: str | None,
    ) -> StaffLoginResult:
        now = self._now()
        challenge = self.challenge_store.consume_challenge(
            challenge_id,
            self._digest_code(challenge_id, code),
            now,
        )
        if challenge is None:
            raise InvalidOrExpiredCode
        # Um desafio iniciado por outro fluxo para um telefone staff continua
        # sendo prova de posse do mesmo numero; a checagem contra a tabela no
        # momento do confirm e o que autoriza.
        staff = self.staff_store.get_active_staff_by_phone_hash(challenge.phone_hash)
        if staff is None:
            raise InvalidOrExpiredCode

        session_token = secrets.token_urlsafe(32)
        expires_at = next_session_cutoff(
            now,
            self.settings.support_console_timezone,
            self.settings.support_staff_session_expiry_hour,
        )
        self.staff_store.create_session(
            self._digest_identity(session_token),
            staff.id,
            now,
            expires_at,
        )
        hint_cookie_value = self._issue_hint(staff, challenge.phone_hash, phone, hint_cookie, now)
        return StaffLoginResult(
            principal=StaffPrincipal(
                staff_id=staff.id,
                display_name=staff.display_name,
                expires_at=expires_at,
            ),
            session_token=session_token,
            hint_cookie_value=hint_cookie_value,
        )

    def get_session(self, session_token: str | None) -> StaffPrincipal | None:
        if not session_token:
            return None
        return self.staff_store.get_session_principal(
            self._digest_identity(session_token),
            self._now(),
        )

    def get_hint_display_name(self, hint_cookie: str | None) -> str | None:
        """Resolve the device hint for the login screen's 1-click button."""

        staff = self._resolve_hint_staff(hint_cookie, self._now())
        return staff.display_name if staff is not None else None

    def logout(
        self,
        *,
        session_token: str | None,
        forget_hint_cookie: str | None = None,
    ) -> None:
        if session_token:
            self.staff_store.delete_session(self._digest_identity(session_token))
        parsed = parse_hint_cookie_value(forget_hint_cookie)
        if parsed is not None:
            self.staff_store.delete_hint(self._digest_identity(parsed[0]))

    def _resolve_hint_staff(
        self,
        hint_cookie: str | None,
        now: datetime,
    ) -> StaffMember | None:
        """Hint token must exist for an active staff AND the phone in the
        cookie must hash to that staff's registered number. Anything off is
        silently ignored (the UI falls back to asking the phone)."""

        parsed = parse_hint_cookie_value(hint_cookie)
        if parsed is None:
            return None
        opaque_token, hint_phone = parsed
        try:
            normalized_phone = normalize_phone(hint_phone)
        except ValueError:
            return None
        staff = self.staff_store.get_hint_staff(
            self._digest_identity(opaque_token),
            now,
        )
        if staff is None:
            return None
        if staff.phone_hash != self._digest_identity(normalized_phone):
            return None
        return staff

    def _resolve_hint_phone(self, hint_cookie: str | None, now: datetime) -> str | None:
        staff = self._resolve_hint_staff(hint_cookie, now)
        if staff is None:
            return None
        parsed = parse_hint_cookie_value(hint_cookie)
        return normalize_phone(parsed[1]) if parsed else None

    def _issue_hint(
        self,
        staff: StaffMember,
        challenge_phone_hash: str,
        phone: str | None,
        hint_cookie: str | None,
        now: datetime,
    ) -> str | None:
        """Mint (or rotate) the device hint when this request proved possession
        of the raw number — either typed again on confirm or carried by the
        previous hint cookie. Without the raw phone there is nothing safe to
        put in the cookie, so no hint is issued."""

        raw_phone: str | None = None
        if phone and phone.strip():
            try:
                raw_phone = normalize_phone(phone)
            except ValueError:
                raw_phone = None
        if raw_phone is None:
            parsed = parse_hint_cookie_value(hint_cookie)
            if parsed is not None:
                try:
                    raw_phone = normalize_phone(parsed[1])
                except ValueError:
                    raw_phone = None
        if raw_phone is None:
            return None
        if self._digest_identity(raw_phone) != challenge_phone_hash:
            return None

        previous = parse_hint_cookie_value(hint_cookie)
        if previous is not None:
            self.staff_store.delete_hint(self._digest_identity(previous[0]))
        opaque_token = secrets.token_urlsafe(32)
        self.staff_store.save_hint(self._digest_identity(opaque_token), staff.id, now)
        return build_hint_cookie_value(opaque_token, raw_phone)

    def _create_challenge(
        self,
        phone_hash: str,
        normalized_phone: str,
        now: datetime,
    ) -> tuple[OtpChallenge, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = str(uuid4())
        challenge = OtpChallenge(
            id=challenge_id,
            phone_hash=phone_hash,
            phone_last4=normalized_phone[-4:],
            code_digest=self._digest_code(challenge_id, code),
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.otp_code_ttl_seconds),
            attempts_remaining=self.settings.otp_max_attempts,
        )
        self.challenge_store.save_challenge(challenge)
        return challenge, code

    def _digest_identity(self, value: str) -> str:
        return _hmac_digest(self.settings.identity_hash_secret or "", value)

    def _digest_code(self, challenge_id: str, code: str) -> str:
        return _hmac_digest(self.settings.otp_digest_secret or "", f"{challenge_id}:{code}")


class InMemoryStaffAuthStore:
    """Lab/test seam with the same contract as the PostgreSQL store."""

    def __init__(self) -> None:
        self._staff_by_id: dict[str, StaffMember] = {}
        self._sessions: dict[str, tuple[str, datetime, datetime]] = {}
        self._hints: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def add_staff(self, member: StaffMember) -> None:
        with self._lock:
            self._staff_by_id[member.id] = member

    def set_staff_status(self, staff_id: str, status: str) -> None:
        with self._lock:
            member = self._staff_by_id[staff_id]
            self._staff_by_id[staff_id] = StaffMember(
                id=member.id,
                phone_hash=member.phone_hash,
                phone_last4=member.phone_last4,
                display_name=member.display_name,
                status=status,
            )

    def get_active_staff_by_phone_hash(self, phone_hash: str) -> StaffMember | None:
        with self._lock:
            for member in self._staff_by_id.values():
                if member.phone_hash == phone_hash and member.status == "active":
                    return member
        return None

    def create_session(
        self,
        session_hash: str,
        staff_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self._lock:
            self._sessions[session_hash] = (staff_id, created_at, expires_at)

    def get_session_principal(
        self,
        session_hash: str,
        now: datetime,
    ) -> StaffPrincipal | None:
        with self._lock:
            session = self._sessions.get(session_hash)
            if session is None:
                return None
            staff_id, _, expires_at = session
            if expires_at <= now:
                return None
            member = self._staff_by_id.get(staff_id)
            if member is None or member.status != "active":
                return None
            return StaffPrincipal(
                staff_id=member.id,
                display_name=member.display_name,
                expires_at=expires_at,
            )

    def delete_session(self, session_hash: str) -> None:
        with self._lock:
            self._sessions.pop(session_hash, None)

    def delete_expired_sessions(self, now: datetime) -> None:
        with self._lock:
            expired = [
                key
                for key, (_, _, expires_at) in self._sessions.items()
                if expires_at <= now
            ]
            for key in expired:
                self._sessions.pop(key, None)

    def save_hint(self, hint_hash: str, staff_id: str, now: datetime) -> None:
        with self._lock:
            self._hints[hint_hash] = {
                "staff_id": staff_id,
                "created_at": now,
                "last_used_at": None,
            }

    def get_hint_staff(self, hint_hash: str, now: datetime) -> StaffMember | None:
        with self._lock:
            hint = self._hints.get(hint_hash)
            if hint is None:
                return None
            member = self._staff_by_id.get(hint["staff_id"])
            if member is None or member.status != "active":
                return None
            hint["last_used_at"] = now
            return member

    def delete_hint(self, hint_hash: str) -> None:
        with self._lock:
            self._hints.pop(hint_hash, None)

    def delete_expired_hints(self, cutoff: datetime) -> None:
        with self._lock:
            expired = [
                key
                for key, hint in self._hints.items()
                if hint["created_at"] <= cutoff
            ]
            for key in expired:
                self._hints.pop(key, None)


class PostgresStaffAuthStore:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def get_active_staff_by_phone_hash(self, phone_hash: str) -> StaffMember | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, phone_hash, phone_last4, display_name, status
                    FROM staff_members
                    WHERE phone_hash = %s AND status = 'active'
                    """,
                    (phone_hash,),
                )
                return _to_staff_member(cursor.fetchone())

    def create_session(
        self,
        session_hash: str,
        staff_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO staff_sessions (session_hash, staff_id, created_at, expires_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (session_hash, staff_id, created_at, expires_at),
                )

    def get_session_principal(
        self,
        session_hash: str,
        now: datetime,
    ) -> StaffPrincipal | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                # Join on status = 'active': desativar um staff derruba as
                # sessoes vivas dele no request seguinte.
                cursor.execute(
                    """
                    SELECT s.staff_id, m.display_name, s.expires_at
                    FROM staff_sessions s
                    JOIN staff_members m ON m.id = s.staff_id
                    WHERE s.session_hash = %s
                      AND s.expires_at > %s
                      AND m.status = 'active'
                    """,
                    (session_hash, now),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return StaffPrincipal(
            staff_id=str(row[0]),
            display_name=str(row[1]),
            expires_at=row[2],
        )

    def delete_session(self, session_hash: str) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM staff_sessions WHERE session_hash = %s",
                    (session_hash,),
                )

    def delete_expired_sessions(self, now: datetime) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM staff_sessions WHERE expires_at <= %s",
                    (now,),
                )

    def save_hint(self, hint_hash: str, staff_id: str, now: datetime) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO staff_login_hints (hint_hash, staff_id, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (hint_hash) DO NOTHING
                    """,
                    (hint_hash, staff_id, now),
                )

    def get_hint_staff(self, hint_hash: str, now: datetime) -> StaffMember | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.id, m.phone_hash, m.phone_last4, m.display_name, m.status
                    FROM staff_login_hints h
                    JOIN staff_members m ON m.id = h.staff_id
                    WHERE h.hint_hash = %s AND m.status = 'active'
                    """,
                    (hint_hash,),
                )
                member = _to_staff_member(cursor.fetchone())
                if member is not None:
                    cursor.execute(
                        "UPDATE staff_login_hints SET last_used_at = %s WHERE hint_hash = %s",
                        (now, hint_hash),
                    )
                return member

    def delete_hint(self, hint_hash: str) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM staff_login_hints WHERE hint_hash = %s",
                    (hint_hash,),
                )

    def delete_expired_hints(self, cutoff: datetime) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM staff_login_hints WHERE created_at <= %s",
                    (cutoff,),
                )


@dataclass(frozen=True)
class SupportConsoleRuntime:
    service: StaffConsoleAuthService
    delivery: OtpDeliveryAdapter
    reads_limiter: InMemoryRateLimiter
    # Ponte WhatsApp<->console: limite do compositor, por caso (nao por
    # sessao staff -- varios operadores nao devem somar limite por caso).
    reply_limiter: InMemoryRateLimiter


def create_support_console_runtime(
    settings: Settings,
    database_runtime: DatabaseRuntime | None = None,
) -> SupportConsoleRuntime:
    """PostgreSQL stores when persistence is on (tabelas da migration 014);
    in-memory seams otherwise (lab/testes). O adapter de entrega e o mesmo do
    OTP de cliente, gateado pela flag do console."""

    from app.web_auth.runtime import create_otp_delivery_adapter
    from app.web_auth.storage import InMemoryWebAuthStore, PostgresWebAuthStore

    use_postgres = (
        settings.persistence_backend == "postgres" and database_runtime is not None
    )
    staff_store: StaffAuthStore = (
        PostgresStaffAuthStore(database_runtime)
        if use_postgres
        else InMemoryStaffAuthStore()
    )
    challenge_store: WebAuthStore = (
        PostgresWebAuthStore(database_runtime)
        if use_postgres
        else InMemoryWebAuthStore()
    )
    delivery = create_otp_delivery_adapter(
        settings,
        enabled=settings.enable_support_console,
    )
    return SupportConsoleRuntime(
        service=StaffConsoleAuthService(
            settings=settings,
            staff_store=staff_store,
            challenge_store=challenge_store,
            delivery=delivery,
        ),
        delivery=delivery,
        reads_limiter=InMemoryRateLimiter(
            max_requests=settings.support_console_reads_per_session_per_minute,
            window_seconds=60,
        ),
        reply_limiter=InMemoryRateLimiter(
            max_requests=settings.support_wa_reply_rate_limit_per_case_per_minute,
            window_seconds=60,
        ),
    )


def _to_staff_member(row: Any) -> StaffMember | None:
    if row is None:
        return None
    return StaffMember(
        id=str(row[0]),
        phone_hash=str(row[1]),
        phone_last4=str(row[2]),
        display_name=str(row[3]),
        status=str(row[4]),
    )
