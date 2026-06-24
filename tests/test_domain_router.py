from __future__ import annotations

from app.core.config import Settings
from app.db.operational import ChatPersistenceResult
from app.integrations.meta_whatsapp.chat_transport import MetaWhatsAppChatTransport
from app.integrations.meta_whatsapp.schemas import MetaInboundTextMessage, MetaSendResult
from app.orchestration.domain_router import DomainRouter, RoutableDomain
from app.orchestration.session_domain_store import InMemorySessionDomainStore


SUPPORT = RoutableDomain(
    name="suporte-vps-whatsapp",
    display_name="Suporte VPS e WhatsApp",
    keywords=("vps", "ssh", "whatsapp", "evolution", "webhook", "n8n", "api"),
)
VENDAS = RoutableDomain(
    name="vendas",
    display_name="Vendas HostGator",
    keywords=("hospedagem", "plano", "preco", "comprar", "contratar", "dominio"),
)


def _router() -> DomainRouter:
    return DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")


def test_menu_selection_by_number() -> None:
    assert _router().route("1").domain == "suporte-vps-whatsapp"
    decision = _router().route("2")
    assert decision.domain == "vendas"
    assert decision.reason == "menu_selection"


def test_menu_selection_by_label() -> None:
    assert _router().route("vendas").domain == "vendas"
    assert _router().route("quero suporte").domain == "suporte-vps-whatsapp"


def test_keyword_routing_to_vendas() -> None:
    decision = _router().route("Quero contratar um plano de hospedagem")
    assert decision.domain == "vendas"
    assert decision.reason == "keyword_match"


def test_keyword_routing_to_support() -> None:
    decision = _router().route("Minha VPS caiu e da erro de ssh")
    assert decision.domain == "suporte-vps-whatsapp"
    assert decision.reason == "keyword_match"


def test_accents_are_normalized() -> None:
    assert _router().route("quero saber o preço").domain == "vendas"


def test_greeting_shows_menu() -> None:
    decision = _router().route("Oi")
    assert decision.show_menu is True
    assert decision.domain is None


def test_blank_shows_menu() -> None:
    assert _router().route("   ").show_menu is True


def test_ambiguous_tie_shows_menu() -> None:
    # one support keyword (vps) and one vendas keyword (hospedagem) -> tie -> menu
    assert _router().route("tenho uma vps e quero hospedagem").show_menu is True


def test_keyword_uses_word_boundaries_not_substring() -> None:
    # "rapido" contains the substring "api" but must NOT trigger the support
    # keyword "api"; with no real keyword match the router falls back to the menu.
    decision = _router().route("quero algo bem rapido")
    assert decision.domain != "suporte-vps-whatsapp"
    assert decision.show_menu is True


def test_single_domain_never_shows_menu() -> None:
    router = DomainRouter(domains=(SUPPORT,), default_domain="suporte-vps-whatsapp")
    decision = router.route("qualquer coisa")
    assert decision.show_menu is False
    assert decision.domain == "suporte-vps-whatsapp"


def test_menu_text_lists_options() -> None:
    text = _router().menu_text()
    assert "1) Suporte VPS e WhatsApp" in text
    assert "2) Vendas HostGator" in text


def test_from_domain_configs_reads_routing_keywords() -> None:
    class FakeRouting:
        keywords = ["hospedagem", "plano"]

    class FakeConfig:
        name = "vendas"
        display_name = "Vendas HostGator"
        routing = FakeRouting()

    router = DomainRouter.from_domain_configs(
        [FakeConfig(), FakeConfig()],
        default_domain="vendas",
    )
    assert router.domains[0].keywords == ("hospedagem", "plano")


# --- transport integration with routing enabled -------------------------------


class _FakeDomainLoader:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def load(self, domain_name: str):
        self.loaded.append(domain_name)
        return object()


class _FakeChatService:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def called(self) -> bool:
        return self.calls > 0

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
        return ChatPersistenceResult(
            handoff_status="handoff_not_required",
            persistence_status="persisted",
            turn_id="turn-id",
        )


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, *, to: str, text: str) -> MetaSendResult:
        self.sent.append(text)
        return MetaSendResult(message_id="wamid.outbound")


def _transport(client, chat, loader):
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    return MetaWhatsAppChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=chat,
        repository=_FakeRepository(),
        router=router,
    )


def _message(text: str) -> MetaInboundTextMessage:
    return MetaInboundTextMessage(
        message_id="wamid.inbound",
        from_wa_id="5511999999999",
        timestamp="1710000000",
        text=text,
    )


def test_transport_greeting_sends_menu_without_calling_engine() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(message=_message("Oi"), request_id="req")

    assert chat.called is False
    assert result.handoff_status == "routing_menu"
    assert "Vendas HostGator" in client.sent[0]


def test_transport_routes_sales_message_to_vendas_domain() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(
        message=_message("Quero contratar um plano de hospedagem"),
        request_id="req",
    )

    assert chat.called is True
    assert "vendas" in loader.loaded
    assert result.outbound_message_id == "wamid.outbound"


# --- sticky session memory ----------------------------------------------------


def test_is_reset_detects_reset_words() -> None:
    r = _router()
    assert r.is_reset("menu") is True
    assert r.is_reset("quero trocar") is True
    assert r.is_reset("voltar") is True
    assert r.is_reset("quero contratar um plano") is False
    # "opcoes" inside a normal question must NOT reset (regression).
    assert r.is_reset("Quais opcoes voce tem para meu site?") is False
    assert r.is_reset("opcoes") is False


def test_in_memory_store_set_get_clear() -> None:
    store = InMemorySessionDomainStore()
    assert store.get("s1") is None
    store.set("s1", "vendas")
    assert store.get("s1") == "vendas"
    store.clear("s1")
    assert store.get("s1") is None


def test_in_memory_store_respects_ttl() -> None:
    import time

    store = InMemorySessionDomainStore(ttl_seconds=10)
    store.set("s1", "vendas")
    # Force the entry to look expired without sleeping.
    store._entries["s1"] = ("vendas", time.monotonic() - 1)
    assert store.get("s1") is None


def _sticky_transport(client, chat, loader, store):
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )
    router = DomainRouter(domains=(SUPPORT, VENDAS), default_domain="suporte-vps-whatsapp")
    return MetaWhatsAppChatTransport(
        settings=settings,
        database_runtime=object(),
        client=client,
        domain_loader=loader,
        chat_service=chat,
        repository=_FakeRepository(),
        router=router,
        session_store=store,
    )


def test_sticky_follow_up_stays_in_chosen_domain() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    store = InMemorySessionDomainStore()
    transport = _sticky_transport(client, chat, loader, store)

    # 1) explicit menu choice -> welcome, sticks to vendas, the chooser is NOT
    #    fed to the brain
    first = transport.handle_text_message(message=_message("2"), request_id="r1")
    assert first.handoff_status == "routing_selected"
    assert chat.calls == 0

    # 2) generic follow-up with no keyword -> sticks to vendas, engine answers
    result = transport.handle_text_message(
        message=_message("pode me explicar melhor?"),
        request_id="r2",
    )
    assert loader.loaded[-1] == "vendas"
    assert chat.calls == 1
    assert result.handoff_status != "routing_menu"


def test_reset_drops_stickiness_and_shows_menu() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    store = InMemorySessionDomainStore()
    transport = _sticky_transport(client, chat, loader, store)

    transport.handle_text_message(message=_message("2"), request_id="r1")
    session_key = next(iter(store._entries))
    assert session_key.startswith("whatsapp:meta:")
    assert "5511999999999" not in session_key  # key is the sanitized hash, not raw wa_id
    assert store.get(session_key) == "vendas"

    # reset -> menu, engine not called, binding cleared
    calls_before = chat.calls
    result = transport.handle_text_message(message=_message("menu"), request_id="r2")
    assert result.handoff_status == "routing_menu"
    assert chat.calls == calls_before
    assert store.get(session_key) is None

    # after reset, a generic message has no sticky domain -> menu again
    result2 = transport.handle_text_message(
        message=_message("pode me explicar melhor?"),
        request_id="r3",
    )
    assert result2.handoff_status == "routing_menu"
