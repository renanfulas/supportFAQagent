from datetime import UTC, datetime, timedelta
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.identity.current import CurrentIdentityResolver
from app.main import create_app
from app.web_auth.delivery import OtpDeliveryUnavailable


PHONE = "+5511999999999"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def enabled_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ENABLE_WEB_WHATSAPP_AUTH", "true")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "identity-secret")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "otp-secret")
    return TestClient(create_app())


def _start(client: TestClient, phone: str = PHONE):
    return client.post("/web/auth/whatsapp/start", json={"phone": phone})


def _delivered_code(client: TestClient) -> str:
    return client.app.state.web_auth_runtime.delivery.requests[-1].code


def _different_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_web_auth_is_hidden_when_disabled() -> None:
    response = TestClient(create_app()).get("/web/auth/session")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_start_returns_pending_challenge_and_sets_http_only_cookie(
    enabled_client: TestClient,
) -> None:
    response = _start(enabled_client)

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["expires_in_seconds"] == 300
    assert response.json()["retry_after_seconds"] == 60
    # Sprint 4b: lets the widget show a client-side "still there?" nudge without
    # a server-side reminder job (the raw phone is never persisted long enough
    # for one to know who to re-contact).
    assert response.json()["abandonment_reminder_seconds"] == 15 * 60
    assert "HttpOnly" in response.headers["set-cookie"]
    delivery = enabled_client.app.state.web_auth_runtime.delivery.requests[-1]
    assert delivery.phone == PHONE
    assert delivery.challenge_id == response.json()["challenge_id"]
    assert len(delivery.code) == 6


@pytest.mark.parametrize("phone", ["11999999999", "+012345678", "+5511", "+55 11 99999-9999"])
def test_start_rejects_non_e164_phone(enabled_client: TestClient, phone: str) -> None:
    response = _start(enabled_client, phone)

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_phone"


def test_start_rejects_extra_fields(enabled_client: TestClient) -> None:
    response = enabled_client.post(
        "/web/auth/whatsapp/start",
        json={"phone": PHONE, "domain": "should-not-be-public"},
    )

    assert response.status_code == 422


def test_confirm_links_verified_identity_to_browser_session(
    enabled_client: TestClient,
) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]

    response = enabled_client.post(
        "/web/auth/whatsapp/confirm",
        json={"challenge_id": challenge_id, "code": _delivered_code(enabled_client)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "verified", "phone_last4": "9999"}
    assert enabled_client.get("/web/auth/session").json() == {
        "status": "verified",
        "phone_last4": "9999",
    }
    session_id = enabled_client.cookies.get("sfaq_web_session")
    assert session_id is not None
    identity = enabled_client.app.state.web_auth_runtime.service.get_session_identity(
        session_id,
    )
    assert identity is not None
    assert identity.customer_id is not None


def test_confirm_reuses_customer_id_for_same_whatsapp(
    enabled_client: TestClient,
) -> None:
    first_challenge_id = _start(enabled_client).json()["challenge_id"]
    assert (
        enabled_client.post(
            "/web/auth/whatsapp/confirm",
            json={
                "challenge_id": first_challenge_id,
                "code": _delivered_code(enabled_client),
            },
        ).status_code
        == 200
    )
    session_id = enabled_client.cookies.get("sfaq_web_session")
    assert session_id is not None
    service = enabled_client.app.state.web_auth_runtime.service
    first_identity = service.get_session_identity(session_id)
    assert first_identity is not None
    assert first_identity.customer_id is not None

    assert enabled_client.post("/web/auth/logout").status_code == 200
    second_challenge_id = _start(enabled_client).json()["challenge_id"]
    assert (
        enabled_client.post(
            "/web/auth/whatsapp/confirm",
            json={
                "challenge_id": second_challenge_id,
                "code": _delivered_code(enabled_client),
            },
        ).status_code
        == 200
    )
    second_identity = service.get_session_identity(session_id)

    assert second_identity is not None
    assert second_identity.customer_id == first_identity.customer_id


def test_current_identity_resolver_returns_customer_context(
    enabled_client: TestClient,
) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]
    assert (
        enabled_client.post(
            "/web/auth/whatsapp/confirm",
            json={"challenge_id": challenge_id, "code": _delivered_code(enabled_client)},
        ).status_code
        == 200
    )
    session_id = enabled_client.cookies.get("sfaq_web_session")
    assert session_id is not None
    settings = get_settings()

    context = CurrentIdentityResolver(
        settings=settings,
        web_auth_service=enabled_client.app.state.web_auth_runtime.service,
    ).resolve(session_id)

    assert context.authenticated is True
    assert context.customer_id is not None
    assert context.verified_identity_id is not None
    assert context.phone_last4 == "9999"
    assert context.persistence_session_hash is not None
    assert len(context.persistence_session_hash) == 64
    assert context.persistence_session_hash_version == settings.persistence_hash_version


def test_confirm_uses_generic_error_and_consumes_attempts(
    enabled_client: TestClient,
) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]

    response = enabled_client.post(
        "/web/auth/whatsapp/confirm",
        json={
            "challenge_id": challenge_id,
            "code": _different_code(_delivered_code(enabled_client)),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_or_expired_code"
    challenge = enabled_client.app.state.web_auth_runtime.service.store.get_challenge(
        challenge_id,
    )
    assert challenge is not None
    assert challenge.attempts_remaining == 4


def test_confirm_rejects_reused_code(enabled_client: TestClient) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]
    payload = {"challenge_id": challenge_id, "code": _delivered_code(enabled_client)}

    assert enabled_client.post("/web/auth/whatsapp/confirm", json=payload).status_code == 200
    response = enabled_client.post("/web/auth/whatsapp/confirm", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_or_expired_code"


def test_confirm_blocks_challenge_after_max_attempts(enabled_client: TestClient) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]
    wrong_code = _different_code(_delivered_code(enabled_client))

    for _ in range(5):
        response = enabled_client.post(
            "/web/auth/whatsapp/confirm",
            json={"challenge_id": challenge_id, "code": wrong_code},
        )
        assert response.status_code == 400

    challenge = enabled_client.app.state.web_auth_runtime.service.store.get_challenge(
        challenge_id,
    )
    assert challenge is not None
    assert challenge.status == "exhausted"
    assert challenge.attempts_remaining == 0


def test_confirm_rejects_expired_code(enabled_client: TestClient) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]
    challenge = enabled_client.app.state.web_auth_runtime.service.store.get_challenge(
        challenge_id,
    )
    assert challenge is not None
    challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = enabled_client.post(
        "/web/auth/whatsapp/confirm",
        json={"challenge_id": challenge_id, "code": _delivered_code(enabled_client)},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_or_expired_code"


def test_resend_cooldown_returns_retry_after(enabled_client: TestClient) -> None:
    assert _start(enabled_client).status_code == 202

    response = _start(enabled_client)

    assert response.status_code == 429
    assert response.json()["detail"] == "too_many_requests"
    assert int(response.headers["Retry-After"]) >= 1


def test_delivery_failure_is_generic(enabled_client: TestClient) -> None:
    class FailingDelivery:
        def deliver(self, request) -> None:
            raise OtpDeliveryUnavailable

    enabled_client.app.state.web_auth_runtime.service.delivery = FailingDelivery()

    response = _start(enabled_client)

    assert response.status_code == 503
    assert response.json()["detail"] == "otp_delivery_unavailable"
    enabled_client.app.state.web_auth_runtime.service.delivery = (
        enabled_client.app.state.web_auth_runtime.delivery
    )
    assert _start(enabled_client).status_code == 202


def test_logout_returns_session_to_anonymous(enabled_client: TestClient) -> None:
    challenge_id = _start(enabled_client).json()["challenge_id"]
    enabled_client.post(
        "/web/auth/whatsapp/confirm",
        json={"challenge_id": challenge_id, "code": _delivered_code(enabled_client)},
    )

    response = enabled_client.post("/web/auth/logout")

    assert response.json() == {"status": "anonymous"}
    assert enabled_client.get("/web/auth/session").json() == {"status": "anonymous"}


def test_logs_do_not_include_raw_phone_or_code(
    enabled_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        _start(enabled_client)

    combined_logs = " ".join(record.getMessage() for record in caplog.records)
    assert PHONE not in combined_logs
    assert _delivered_code(enabled_client) not in combined_logs


# --------------------------------------------------------------------------- #
# Fase 3 (opcional, opt-in): hash nativo carregado de start() a confirm()
# --------------------------------------------------------------------------- #


def _build_service(*, native_link_enabled: bool, persistence_hash_secret: str | None):
    from types import SimpleNamespace

    from app.web_auth.delivery import InMemoryOtpDeliveryAdapter
    from app.web_auth.service import WebWhatsAppAuthService
    from app.web_auth.storage import InMemoryWebAuthStore

    settings = SimpleNamespace(
        identity_hash_secret="identity-secret",
        otp_digest_secret="otp-secret",
        otp_code_ttl_seconds=300,
        otp_resend_cooldown_seconds=60,
        otp_max_attempts=5,
        otp_start_limit_per_ip_per_hour=10,
        otp_start_limit_per_phone_per_15_minutes=3,
        enable_native_identity_link=native_link_enabled,
        persistence_hash_secret=persistence_hash_secret,
    )
    return WebWhatsAppAuthService(
        settings=settings,
        store=InMemoryWebAuthStore(),
        delivery=InMemoryOtpDeliveryAdapter(),
    )


def test_start_computes_native_hashes_when_flag_and_secret_configured() -> None:
    service = _build_service(
        native_link_enabled=True, persistence_hash_secret="persistence-secret"
    )

    challenge = service.start(phone=PHONE, client_host="1.2.3.4")

    assert challenge.native_session_hash_hermes is not None
    assert challenge.native_session_hash_meta is not None
    assert challenge.native_session_hash_hermes != challenge.native_session_hash_meta


def test_start_skips_native_hashes_when_flag_off() -> None:
    service = _build_service(
        native_link_enabled=False, persistence_hash_secret="persistence-secret"
    )

    challenge = service.start(phone=PHONE, client_host="1.2.3.4")

    assert challenge.native_session_hash_hermes is None
    assert challenge.native_session_hash_meta is None


def test_start_skips_native_hashes_without_persistence_secret() -> None:
    service = _build_service(native_link_enabled=True, persistence_hash_secret=None)

    challenge = service.start(phone=PHONE, client_host="1.2.3.4")

    assert challenge.native_session_hash_hermes is None
    assert challenge.native_session_hash_meta is None


def test_confirm_returns_native_hashes_from_the_consumed_challenge() -> None:
    service = _build_service(
        native_link_enabled=True, persistence_hash_secret="persistence-secret"
    )
    challenge = service.start(phone=PHONE, client_host="1.2.3.4")
    code = service.delivery.requests[-1].code

    confirmed = service.confirm(
        challenge_id=challenge.id, code=code, session_id="session-1"
    )

    assert confirmed.identity.customer_id is not None
    assert confirmed.native_session_hashes is not None
    assert confirmed.native_session_hashes.hermes == challenge.native_session_hash_hermes
    assert confirmed.native_session_hashes.meta == challenge.native_session_hash_meta


def test_confirm_native_hashes_none_when_flag_off() -> None:
    service = _build_service(native_link_enabled=False, persistence_hash_secret="secret")
    challenge = service.start(phone=PHONE, client_host="1.2.3.4")
    code = service.delivery.requests[-1].code

    confirmed = service.confirm(
        challenge_id=challenge.id, code=code, session_id="session-1"
    )

    assert confirmed.native_session_hashes is None
