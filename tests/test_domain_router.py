from __future__ import annotations

from app.core.config import Settings
from app.db.operational import ChatPersistenceResult
from app.integrations.meta_whatsapp.chat_transport import MetaWhatsAppChatTransport
from app.integrations.meta_whatsapp.schemas import MetaInboundTextMessage, MetaSendResult
from app.orchestration.domain_router import DomainRouter, RoutableDomain


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
        self.called = False

    def answer(self, **kwargs):
        self.called = True
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
