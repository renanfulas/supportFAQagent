"""Coverage for the staff console OTP auth service (in-memory seams).

Clock and timezone are injected/fixed so the daily 4am cutoff never flutters
with the environment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.rate_limit import RateLimitExceeded
from app.support.staff_auth import (
    InMemoryStaffAuthStore,
    StaffConsoleAuthService,
    StaffMember,
    StaffPhoneRequired,
    build_hint_cookie_value,
    next_session_cutoff,
    parse_hint_cookie_value,
)
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.service import InvalidOrExpiredCode, _hmac_digest
from app.web_auth.storage import InMemoryWebAuthStore


IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
STAFF_PHONE = "+5511999990001"
OTHER_PHONE = "+5511999990002"


class FakeDelivery:
    def __init__(self) -> None:
        self.requests = []
        self.broken = False

    def deliver(self, request) -> None:
        if self.broken:
            raise OtpDeliveryUnavailable
        self.requests.append(request)


def _settings(**overrides) -> SimpleNamespace:
    values = {
        "identity_hash_secret": IDENTITY_SECRET,
        "otp_digest_secret": OTP_SECRET,
        "otp_code_ttl_seconds": 300,
        "otp_max_attempts": 5,
        # Cooldown zerado por padrao para os fluxos multi-start; o teste de
        # paridade anti-enumeracao liga um cooldown real.
        "otp_resend_cooldown_seconds": 0,
        "support_otp_start_per_phone_per_hour": 10,
        "support_otp_start_per_ip_per_hour": 50,
        "support_console_timezone": "America/Sao_Paulo",
        "support_staff_session_expiry_hour": 4,
        "support_staff_hint_ttl_days": 90,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service(settings=None):
    settings = settings or _settings()
    clock = [datetime(2026, 7, 2, 18, 0, tzinfo=UTC)]
    staff_store = InMemoryStaffAuthStore()
    staff_store.add_staff(
        StaffMember(
            id=str(uuid4()),
            phone_hash=_hmac_digest(IDENTITY_SECRET, STAFF_PHONE),
            phone_last4=STAFF_PHONE[-4:],
            display_name="Renan",
        )
    )
    delivery = FakeDelivery()
    service = StaffConsoleAuthService(
        settings=settings,
        staff_store=staff_store,
        challenge_store=InMemoryWebAuthStore(),
        delivery=delivery,
        now=lambda: clock[0],
    )
    return service, staff_store, delivery, clock


def _login(service, delivery, *, phone=STAFF_PHONE):
    start = service.start(phone=phone, hint_cookie=None, client_host="10.0.0.1")
    code = delivery.requests[-1].code
    return service.confirm(
        challenge_id=start.challenge_id,
        code=code,
        phone=phone,
        hint_cookie=None,
    )


# --------------------------------------------------------------------------- #
# Fluxo staff completo + sessao diaria
# --------------------------------------------------------------------------- #


def test_full_staff_flow_creates_session_until_next_4am_team_time() -> None:
    service, _, delivery, clock = _service()

    login = _login(service, delivery)

    assert login.principal.display_name == "Renan"
    # 2026-07-02 18:00 UTC = 15:00 em Sao Paulo (UTC-3); proxima 4h local
    # e 2026-07-03 04:00 -03:00 = 07:00 UTC.
    assert login.principal.expires_at == datetime(2026, 7, 3, 7, 0, tzinfo=UTC)

    principal = service.get_session(login.session_token)
    assert principal is not None
    assert principal.display_name == "Renan"

    # A sessao morre exatamente no corte, sem renovacao deslizante.
    clock[0] = datetime(2026, 7, 3, 7, 0, tzinfo=UTC)
    assert service.get_session(login.session_token) is None


def test_session_that_starts_just_before_cutoff_expires_at_same_day_4am() -> None:
    cutoff = next_session_cutoff(
        datetime(2026, 7, 3, 6, 59, tzinfo=UTC),  # 03:59 em Sao Paulo
        "America/Sao_Paulo",
        4,
    )
    assert cutoff == datetime(2026, 7, 3, 7, 0, tzinfo=UTC)


def test_multiple_sessions_per_operator_are_allowed() -> None:
    service, _, delivery, _ = _service()

    desktop = _login(service, delivery)
    notebook = _login(service, delivery)

    assert service.get_session(desktop.session_token) is not None
    assert service.get_session(notebook.session_token) is not None


def test_disabled_staff_loses_live_sessions_and_hints() -> None:
    service, staff_store, delivery, _ = _service()
    login = _login(service, delivery)
    assert login.hint_cookie_value is not None

    staff_store.set_staff_status(login.principal.staff_id, "disabled")

    assert service.get_session(login.session_token) is None
    assert service.get_hint_display_name(login.hint_cookie_value) is None
    with pytest.raises(InvalidOrExpiredCode):
        # Confirm de um desafio ja iniciado tambem nega apos desativacao.
        start = service.start(
            phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1"
        )
        service.confirm(
            challenge_id=start.challenge_id,
            code="000000",
            phone=STAFF_PHONE,
            hint_cookie=None,
        )


# --------------------------------------------------------------------------- #
# Anti-enumeracao
# --------------------------------------------------------------------------- #


def test_non_staff_start_returns_synthetic_challenge_without_delivery() -> None:
    service, _, delivery, _ = _service()

    result = service.start(
        phone=OTHER_PHONE, hint_cookie=None, client_host="10.0.0.1"
    )

    assert result.staff_match is False
    assert result.challenge_id
    assert delivery.requests == []
    with pytest.raises(InvalidOrExpiredCode):
        service.confirm(
            challenge_id=result.challenge_id,
            code="123456",
            phone=OTHER_PHONE,
            hint_cookie=None,
        )


def test_resend_cooldown_applies_equally_to_staff_and_non_staff() -> None:
    service, _, _, _ = _service(_settings(otp_resend_cooldown_seconds=60))

    service.start(phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1")
    with pytest.raises(RateLimitExceeded):
        service.start(phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1")

    service.start(phone=OTHER_PHONE, hint_cookie=None, client_host="10.0.0.2")
    with pytest.raises(RateLimitExceeded):
        service.start(phone=OTHER_PHONE, hint_cookie=None, client_host="10.0.0.2")


def test_delivery_failure_never_changes_the_start_result_shape() -> None:
    service, _, delivery, _ = _service()
    delivery.broken = True

    result = service.start(
        phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1"
    )

    assert result.staff_match is True
    assert result.delivery_failed is True
    assert result.challenge_id


# --------------------------------------------------------------------------- #
# Lembrete de dispositivo (1 clique)
# --------------------------------------------------------------------------- #


def test_hint_allows_start_without_typing_the_phone() -> None:
    service, _, delivery, _ = _service()
    login = _login(service, delivery)

    result = service.start(
        phone=None, hint_cookie=login.hint_cookie_value, client_host="10.0.0.1"
    )

    assert result.staff_match is True
    assert delivery.requests[-1].phone == STAFF_PHONE
    assert service.get_hint_display_name(login.hint_cookie_value) == "Renan"


def test_hint_alone_never_authenticates() -> None:
    service, _, delivery, _ = _service()
    login = _login(service, delivery)

    # O valor do lembrete nao e uma sessao: nao lista casos, nao vira principal.
    assert service.get_session(login.hint_cookie_value) is None


def test_tampered_hint_phone_is_ignored() -> None:
    service, _, delivery, _ = _service()
    login = _login(service, delivery)
    opaque_token, _ = parse_hint_cookie_value(login.hint_cookie_value)
    forged = build_hint_cookie_value(opaque_token, OTHER_PHONE)

    # Telefone trocado quebra o vinculo com o phone_hash do staff: o lembrete
    # e ignorado e, sem telefone digitado, o start pede o telefone.
    with pytest.raises(StaffPhoneRequired):
        service.start(phone=None, hint_cookie=forged, client_host="10.0.0.1")
    assert service.get_hint_display_name(forged) is None


def test_unknown_hint_token_is_ignored() -> None:
    service, _, _, _ = _service()
    forged = build_hint_cookie_value("stolen-token", STAFF_PHONE)

    with pytest.raises(StaffPhoneRequired):
        service.start(phone=None, hint_cookie=forged, client_host="10.0.0.1")


def test_one_click_login_rotates_the_hint() -> None:
    service, _, delivery, _ = _service()
    first = _login(service, delivery)

    start = service.start(
        phone=None, hint_cookie=first.hint_cookie_value, client_host="10.0.0.1"
    )
    second = service.confirm(
        challenge_id=start.challenge_id,
        code=delivery.requests[-1].code,
        phone=None,
        hint_cookie=first.hint_cookie_value,
    )

    assert second.hint_cookie_value is not None
    assert second.hint_cookie_value != first.hint_cookie_value
    assert service.get_hint_display_name(second.hint_cookie_value) == "Renan"
    # O lembrete antigo foi rotacionado fora.
    assert service.get_hint_display_name(first.hint_cookie_value) is None


def test_confirm_without_raw_phone_creates_session_but_no_hint() -> None:
    service, _, delivery, _ = _service()
    start = service.start(
        phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1"
    )

    login = service.confirm(
        challenge_id=start.challenge_id,
        code=delivery.requests[-1].code,
        phone=None,
        hint_cookie=None,
    )

    assert login.hint_cookie_value is None
    assert service.get_session(login.session_token) is not None


# --------------------------------------------------------------------------- #
# Logout
# --------------------------------------------------------------------------- #


def test_logout_kills_session_but_preserves_hint() -> None:
    service, _, delivery, _ = _service()
    login = _login(service, delivery)

    service.logout(session_token=login.session_token)

    assert service.get_session(login.session_token) is None
    assert service.get_hint_display_name(login.hint_cookie_value) == "Renan"


def test_logout_with_forget_device_removes_the_hint() -> None:
    service, _, delivery, _ = _service()
    login = _login(service, delivery)

    service.logout(
        session_token=login.session_token,
        forget_hint_cookie=login.hint_cookie_value,
    )

    assert service.get_hint_display_name(login.hint_cookie_value) is None


# --------------------------------------------------------------------------- #
# Limpeza oportunista
# --------------------------------------------------------------------------- #


def test_start_purges_expired_sessions() -> None:
    service, staff_store, delivery, clock = _service()
    login = _login(service, delivery)

    clock[0] = clock[0] + timedelta(days=2)
    service.start(phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1")

    assert staff_store._sessions == {}


def test_start_purges_hints_older_than_ttl() -> None:
    # Higiene: um lembrete cujo cookie o operador ja descartou nunca expira
    # sozinho no servidor -- a poda oportunista no start pelo mesmo TTL do
    # cookie (90 dias no default) o remove.
    service, staff_store, delivery, clock = _service()
    login = _login(service, delivery)
    assert login.hint_cookie_value is not None
    assert service.get_hint_display_name(login.hint_cookie_value) == "Renan"

    clock[0] = clock[0] + timedelta(days=91)
    service.start(phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1")

    assert staff_store._hints == {}
    assert service.get_hint_display_name(login.hint_cookie_value) is None


def test_start_keeps_hints_within_ttl() -> None:
    service, staff_store, delivery, clock = _service()
    login = _login(service, delivery)

    clock[0] = clock[0] + timedelta(days=30)
    service.start(phone=STAFF_PHONE, hint_cookie=None, client_host="10.0.0.1")

    assert service.get_hint_display_name(login.hint_cookie_value) == "Renan"
