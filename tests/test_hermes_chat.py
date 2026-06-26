from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings, get_settings
from app.core.rate_limit import InMemoryRateLimiter
from app.db.operational import ChatPersistenceResult
from app.integrations.hermes.chat_transport import ESCAPE_STATE, HermesChatTransport
from app.integrations.hermes.client import HermesBridgeClient, HermesSendResult
from app.integrations.hermes.inbound import (
    HermesInboundMessage,
    HermesReplayGuard,
    parse_hermes_inbound,
    verify_hermes_signature,
)
from app.main import create_app
from app.orchestration.domain_router import DomainRouter, RoutableDomain
from app.orchestration.session_domain_store import InMemorySessionDomainStore


SECRET = "hermes-secret"

SUPPORT = RoutableDomain(
    name="suporte-vps-whatsapp",
    display_name="Suporte VPS e WhatsApp",
    keywords=("vps", "ssh", "whatsapp", "n8n"),
)
VENDAS = RoutableDomain(
    name="vendas",
    display_name="Vendas HostGator",
    keywords=("hospedagem", "plano", "preco", "contratar"),
)


# --- inbound contract ---------------------------------------------------------


def test_parse_hermes_inbound_single_bridge_event() -> None:
    parsed = parse_hermes_inbound(
        {
            "messageId": "h1",
            "chatId": "5511999999999@s.whatsapp.net",
            "senderId": "5511999999999@s.whatsapp.net",
            "body": "Oi",
            "isGroup": False,
        }
    )
    assert len(parsed) == 1
    assert parsed[0].message_id == "h1"
    assert parsed[0].chat_id == "5511999999999@s.whatsapp.net"
    assert parsed[0].text == "Oi"


def test_parse_hermes_inbound_batch_ignores_groups_and_empty() -> None:
    payload = {
        "messages": [
            {"messageId": "h1", "chatId": "c1", "senderId": "s1", "body": "oi", "isGroup": False},
            {"messageId": "h2", "chatId": "g1", "senderId": "s2", "body": "ping", "isGroup": True},
            {"messageId": "h3", "chatId": "c3", "senderId": "s3", "body": "", "isGroup": False},
        ]
    }
    assert [m.message_id for m in parse_hermes_inbound(payload)] == ["h1"]


def test_parse_hermes_inbound_ignores_malformed() -> None:
    assert parse_hermes_inbound({}) == []
    assert parse_hermes_inbound({"messageId": "h1", "chatId": "c1"}) == []  # sem body


def test_parse_hermes_inbound_caps_text_length() -> None:
    long_body = "a" * 9000
    parsed = parse_hermes_inbound(
        {"messageId": "h1", "chatId": "c1", "senderId": "s1", "body": long_body},
        max_text_chars=4096,
    )
    assert len(parsed) == 1
    assert len(parsed[0].text) == 4096


def test_replay_guard_blocks_second_identical_signature() -> None:
    guard = HermesReplayGuard(ttl_seconds=300)
    assert guard.check_and_remember("sig-1", now=1_000.0) is True
    # Same signature inside the window is a replay.
    assert guard.check_and_remember("sig-1", now=1_100.0) is False
    # A different signature is independent.
    assert guard.check_and_remember("sig-2", now=1_100.0) is True
    # Once the TTL elapses the signature is forgotten and accepted again.
    assert guard.check_and_remember("sig-1", now=1_400.0) is True
    # An empty signature is never accepted.
    assert guard.check_and_remember("", now=1_000.0) is False


def _sign(body: bytes, ts: str) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_hermes_signature_accepts_fresh_and_rejects_tampered() -> None:
    body = b'{"messages":[]}'
    ts = str(int(datetime.now(UTC).timestamp()))
    assert verify_hermes_signature(body=body, signature=_sign(body, ts), timestamp=ts, secret=SECRET)
    assert not verify_hermes_signature(body=body, signature="bad", timestamp=ts, secret=SECRET)
    # stale timestamp is rejected
    assert not verify_hermes_signature(
        body=body, signature=_sign(body, ts), timestamp="0", secret=SECRET, now=10_000
    )


# --- client send_text ---------------------------------------------------------


def test_hermes_bridge_client_send_text_posts_to_send(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"messageId": "wamid-out"}

    def fake_post(url, *, json, timeout, allow_redirects):
        captured.update(url=url, json=json, allow_redirects=allow_redirects)
        return Response()

    monkeypatch.setattr("app.integrations.hermes.client.requests.post", fake_post)
    client = HermesBridgeClient(base_url="http://127.0.0.1:3000")

    result = client.send_text(to="5511999999999@s.whatsapp.net", text="Oi", message_id="h1")

    assert isinstance(result, HermesSendResult)
    assert result.message_id == "wamid-out"
    assert captured["url"] == "http://127.0.0.1:3000/send"
    assert captured["json"] == {"chatId": "5511999999999@s.whatsapp.net", "message": "Oi"}
    assert captured["allow_redirects"] is False  # never chase redirects (anti-SSRF)


# --- transport (routing + brain reuse) ----------------------------------------


class _FakeDomainLoader:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def load(self, domain_name: str):
        self.loaded.append(domain_name)
        return object()


class _FakeChatService:
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, **kwargs):
        self.calls += 1
        return {
            "domain": "vendas",
            "answer": "Resposta de vendas.",
            "confidence": 0.8,
            "escalated": False,
            "handoff_reasons": [],
            "references": ["hostgator-hospedagem-de-sites.md"],
            "error_code": None,
        }


class _FakeRepository:
    def record_chat(self, audit):
        self.audit = audit
        return ChatPersistenceResult(
            handoff_status="handoff_not_required",
            persistence_status="persisted",
            turn_id="turn-id",
        )


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, *, to: str, text: str, message_id: str) -> HermesSendResult:
        self.sent.append(text)
        return HermesSendResult(message_id="hermes-out")


def _transport(client, chat, loader):
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    return HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=chat,
        repository=_FakeRepository(),
        router=router,
        rate_limiter=InMemoryRateLimiter(max_requests=1000),
    )


def test_transport_rate_limits_per_number() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=chat,
        repository=_FakeRepository(),
        router=router,
        rate_limiter=InMemoryRateLimiter(max_requests=2),
    )
    msg = "quero contratar um plano de hospedagem"
    transport.handle_text_message(message=_msg(msg), request_id="r1")
    transport.handle_text_message(message=_msg(msg), request_id="r2")
    third = transport.handle_text_message(message=_msg(msg), request_id="r3")

    assert third.handoff_status == "rate_limited"
    assert chat.calls == 2  # so o excesso e descartado, sem chamar o LLM


def _msg(text: str) -> HermesInboundMessage:
    return HermesInboundMessage(
        message_id="h1",
        from_wa_id="5511999999999@s.whatsapp.net",
        chat_id="5511999999999@s.whatsapp.net",
        text=text,
    )


def test_transport_routes_sales_and_reuses_brain() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(
        message=_msg("quero contratar um plano de hospedagem"),
        request_id="r1",
    )

    assert chat.calls == 1
    assert "vendas" in loader.loaded
    assert client.sent == ["Resposta de vendas."]
    assert result.outbound_message_id == "hermes-out"


def test_transport_greeting_sends_menu_without_brain() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(message=_msg("Oi"), request_id="r1")

    assert chat.calls == 0
    assert result.handoff_status == "routing_menu"
    assert "Vendas HostGator" in client.sent[0]


def test_transport_menu_selection_sends_welcome_without_brain() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(message=_msg("2"), request_id="r1")

    assert chat.calls == 0  # the chooser "2" must not be fed to the brain
    assert result.handoff_status == "routing_selected"
    assert "Vendas HostGator" in client.sent[0]


class _OutOfScopeChat:
    def answer(self, **kwargs):
        return {
            "domain": "vendas",
            "answer": "Nao posso atuar fora do escopo deste dominio.",
            "confidence": 0.0,
            "escalated": True,
            "handoff_reasons": ["out_of_scope"],
            "references": [],
            "error_code": None,
        }


def _escape_transport():
    client, loader = _FakeClient(), _FakeDomainLoader()
    store = InMemorySessionDomainStore()
    state = InMemorySessionDomainStore()
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=_OutOfScopeChat(),
        repository=_FakeRepository(),
        router=router,
        session_store=store,
        state_store=state,
        rate_limiter=InMemoryRateLimiter(max_requests=1000),
    )
    return transport, client, store, state


def test_out_of_scope_offers_escape_then_2_closes_and_resets() -> None:
    transport, client, store, state = _escape_transport()

    # A routed message that comes back out_of_scope gets the escape options.
    transport.handle_text_message(message=_msg("preciso de hospedagem"), request_id="r1")
    assert "1) Resolver com um atendente" in client.sent[-1]
    assert "2) Encerrar atendimento" in client.sent[-1]
    session_key = next(iter(state._entries))
    assert state.get(session_key) == ESCAPE_STATE
    store.set(session_key, "vendas")

    # "2" closes and resets both the sticky domain and the escape state.
    result = transport.handle_text_message(message=_msg("2"), request_id="r2")
    assert result.handoff_status == "closed"
    assert "encerrado" in client.sent[-1].lower()
    assert state.get(session_key) is None
    assert store.get(session_key) is None


def test_repeated_message_is_replaced_by_reflection_nudge() -> None:
    client, loader = _FakeClient(), _FakeDomainLoader()
    store = InMemorySessionDomainStore()
    state = InMemorySessionDomainStore()
    last_out = InMemorySessionDomainStore()
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=_OutOfScopeChat(),
        repository=_FakeRepository(),
        router=router,
        session_store=store,
        state_store=state,
        last_out_store=last_out,
        rate_limiter=InMemoryRateLimiter(max_requests=1000),
    )

    transport.handle_text_message(message=_msg("preciso de hospedagem"), request_id="r1")
    first = client.sent[-1]
    result = transport.handle_text_message(message=_msg("preciso de hospedagem"), request_id="r2")
    second = client.sent[-1]

    assert first != second  # the exact same message was not repeated
    assert "me conta em uma frase" in second.lower()  # reflection nudge instead
    assert result.handoff_status == "repeat_reflection"


def test_escape_option_1_routes_to_human() -> None:
    transport, client, store, state = _escape_transport()
    transport.handle_text_message(message=_msg("preciso de hospedagem"), request_id="r1")

    result = transport.handle_text_message(message=_msg("1"), request_id="r2")
    assert result.handoff_status == "human_requested"
    assert "atendente humano" in client.sent[-1].lower()


def test_session_id_is_hashed_not_raw() -> None:
    from app.integrations.hermes.chat_transport import _safe_hermes_session_id

    sid = _safe_hermes_session_id("5511999999999")
    assert sid.startswith("whatsapp:hermes:")
    assert "5511999999999" not in sid


# --- route gating + signature -------------------------------------------------


def test_chat_webhook_404_when_disabled() -> None:
    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/integrations/hermes/chat/webhook", content=b"{}")
    assert resp.status_code == 404
    get_settings.cache_clear()


def test_chat_webhook_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    body = b'{"messages":[{"from":"5511999999999","id":"h1","type":"text","text":"Oi"}]}'
    resp = client.post(
        "/integrations/hermes/chat/webhook",
        content=body,
        headers={"X-Webhook-Signature": "bad", "X-Webhook-Timestamp": "0"},
    )
    assert resp.status_code == 401
    get_settings.cache_clear()


def test_chat_webhook_rejects_proxied_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # A request that came through the public reverse proxy carries X-Forwarded-For;
    # the internal webhook must 404 it (only the direct local bridge may call it).
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    resp = client.post(
        "/integrations/hermes/chat/webhook",
        content=b'{"messages":[]}',
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert resp.status_code == 404
    get_settings.cache_clear()


def test_chat_webhook_uses_segregated_forward_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # When a dedicated forward secret is set, the OTP secret must NOT validate.
    forward_secret = "forward-secret-distinct"
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("HERMES_CHAT_FORWARD_SECRET", forward_secret)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    body = b'{"messages":[]}'
    ts = str(int(datetime.now(UTC).timestamp()))

    def sign(secret: str) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    ok = client.post(
        "/integrations/hermes/chat/webhook",
        content=body,
        headers={"X-Webhook-Signature": sign(forward_secret), "X-Webhook-Timestamp": ts},
    )
    assert ok.status_code == 200

    otp_signed = client.post(
        "/integrations/hermes/chat/webhook",
        content=body,
        headers={"X-Webhook-Signature": sign(SECRET), "X-Webhook-Timestamp": ts},
    )
    assert otp_signed.status_code == 401
    get_settings.cache_clear()


def test_chat_webhook_rejects_replayed_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    # An identical signed request (same body, same signature) must be accepted once and
    # rejected on replay within the freshness window.
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    body = b'{"messages":[]}'
    ts = str(int(datetime.now(UTC).timestamp()))
    headers = {"X-Webhook-Signature": _sign(body, ts), "X-Webhook-Timestamp": ts}

    first = client.post("/integrations/hermes/chat/webhook", content=body, headers=headers)
    assert first.status_code == 200

    replay = client.post("/integrations/hermes/chat/webhook", content=body, headers=headers)
    assert replay.status_code == 409
    get_settings.cache_clear()


def test_chat_webhook_rejects_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    # Over the 256 KB cap: rejected via the Content-Length pre-check before any
    # signature work, so no valid signature is needed.
    body = b'{"x":"' + b"a" * 300_000 + b'"}'
    resp = client.post("/integrations/hermes/chat/webhook", content=body)
    assert resp.status_code == 413
    get_settings.cache_clear()


def test_chat_webhook_rejects_too_many_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_HERMES_CHAT", "true")
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.local")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    client = TestClient(create_app(), raise_server_exceptions=False)

    events = [
        {"messageId": f"h{i}", "chatId": "c", "senderId": "s", "body": "oi", "isGroup": False}
        for i in range(26)
    ]
    body = json.dumps({"messages": events}, separators=(",", ":")).encode()
    ts = str(int(datetime.now(UTC).timestamp()))
    resp = client.post(
        "/integrations/hermes/chat/webhook",
        content=body,
        headers={"X-Webhook-Signature": _sign(body, ts), "X-Webhook-Timestamp": ts},
    )
    assert resp.status_code == 400
    get_settings.cache_clear()
