from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.operational import ChatPersistenceResult
from app.domain_engine.loader import DomainLoader
from app.domain_engine.models import DomainConfig
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


def test_greeting_text_introduces_company_and_steers_domains() -> None:
    text = _router().greeting_text()
    assert "HostGator Brasil" in text
    assert "assistente virtual" in text
    assert "suporte tecnico" in text
    assert "planos" in text
    # The greeting is conversational: no numbered menu lines.
    assert "1)" not in text


def test_clarification_text_asks_support_or_sales() -> None:
    text = _router().clarification_text()
    assert "suporte tecnico" in text
    assert "planos" in text
    assert text != _router().greeting_text()


def test_welcome_text_uses_custom_when_set() -> None:
    custom = RoutableDomain(
        name="vendas",
        display_name="Vendas HostGator",
        welcome="Somos a HostGator. Como posso te ajudar hoje?",
    )
    router = DomainRouter(domains=(SUPPORT, custom), default_domain="suporte-vps-whatsapp")
    assert router.welcome_text("vendas") == "Somos a HostGator. Como posso te ajudar hoje?"
    # a domain without a custom welcome falls back to the generic greeting
    assert "Suporte VPS e WhatsApp" in router.welcome_text("suporte-vps-whatsapp")


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


# --- regressao de roteamento com os configs reais dos dominios ----------------
# Garante que a poda de keywords do vendas (Fase 2) e as keywords tecnicas do
# suporte-hospedagem nao se sequestram. Usa os domain.yaml reais, entao quebra se
# alguem reintroduzir uma colisao generica.


def _real_router() -> DomainRouter:
    loader = DomainLoader(Path("domains"))
    names = ["suporte-vps-whatsapp", "vendas", "suporte-hospedagem", "suporte-vps"]
    configs = [config for name in names if (config := loader.load(name)) is not None]
    assert len(configs) == len(names), "todos os dominios roteados devem carregar"
    return DomainRouter.from_domain_configs(configs, default_domain="suporte-vps-whatsapp")


@pytest.mark.parametrize(
    "text, expected_domain",
    [
        ("Quero contratar um plano de hospedagem", "vendas"),
        ("Quanto custa o upgrade do meu plano?", "vendas"),
        ("Meu cPanel nao abre", "suporte-hospedagem"),
        ("Meu site WordPress esta com tela branca", "suporte-hospedagem"),
        ("Como edito o htaccess no cPanel?", "suporte-hospedagem"),
        ("Meu site esta dando erro 500", "suporte-hospedagem"),
        ("Como instalo a Evolution API no n8n da minha VPS?", "suporte-vps-whatsapp"),
        ("O QR Code do WhatsApp nao conecta", "suporte-vps-whatsapp"),
        # suporte-vps (gerenciamento/ciclo de vida) roteia pelos discriminadores,
        # mesmo com "vps" sendo termo compartilhado (ambient) e portanto ignorado.
        ("Como reinstalo o sistema operacional da minha VPS?", "suporte-vps"),
        ("Preciso fazer o rebuild da minha VPS", "suporte-vps"),
        ("Como acesso meu Servidor Dedicado Windows por RDP?", "suporte-vps"),
    ],
)
def test_real_configs_route_to_expected_domain(text: str, expected_domain: str) -> None:
    decision = _real_router().route(text)
    assert decision.domain == expected_domain, (text, decision.reason)


def test_real_configs_wordpress_is_owned_by_support_not_vendas() -> None:
    # Regressao da Fase 2: "wordpress" foi removido das keywords de vendas, entao
    # uma duvida tecnica de WordPress nao pode mais cair em vendas.
    decision = _real_router().route("preciso resolver um erro no meu wordpress")
    assert decision.domain == "suporte-hospedagem"


def test_real_configs_bare_hospedagem_term_is_ambiguous_and_shows_menu() -> None:
    # "hospedagem" continua em vendas (ancora comercial), entao uma frase tecnica
    # que so cite "hospedagem" empata com o sinal tecnico e cai no menu (fallback
    # seguro), em vez de adivinhar. Documenta a fronteira conhecida da Fase 2.
    decision = _real_router().route("Como edito o htaccess da hospedagem?")
    assert decision.show_menu is True
    assert decision.domain is None


def test_real_configs_bare_vps_is_ambient_and_shows_menu() -> None:
    # "vps" e compartilhado por suporte-vps-whatsapp, vendas e suporte-vps, entao
    # e tratado como ambiente e ignorado no roteamento: uma frase so com "vps" cai
    # no menu em vez de empatar de forma arbitraria.
    decision = _real_router().route("preciso de ajuda com a minha vps")
    assert decision.show_menu is True
    assert decision.domain is None


def test_real_configs_servidor_dedicado_is_ambiguous_with_sales_anchor() -> None:
    # Fronteira conhecida (generico vs especifico): "servidor" e ancora comercial
    # de vendas e "servidor dedicado" e do suporte-vps; sem outro discriminador
    # empata e cai no menu. Seguro: o usuario escolhe.
    decision = _real_router().route("tenho um servidor dedicado")
    assert decision.show_menu is True


# --- mecanismo de unique-keyword routing (com fixtures controladas) -----------


def test_shared_keyword_is_ignored_for_routing() -> None:
    infra = RoutableDomain(name="infra", display_name="Infra", keywords=("vps", "rebuild"))
    auto = RoutableDomain(name="auto", display_name="Auto", keywords=("vps", "evolution"))
    router = DomainRouter(domains=(infra, auto), default_domain="infra")

    # "vps" e compartilhado -> ambiente -> uma mensagem so com "vps" nao decide
    assert router.route("minha vps").show_menu is True
    # os discriminadores unicos ainda decidem
    assert router.route("preciso fazer rebuild na vps").domain == "infra"
    assert router.route("a evolution na vps caiu").domain == "auto"


def test_domain_with_only_shared_keywords_is_not_keyword_routable() -> None:
    # Quebra conhecida: um dominio cujas keywords sao todas compartilhadas nao
    # ganha roteamento por keyword (so por menu/numero). Documentado de proposito.
    only_shared = RoutableDomain(name="a", display_name="A", keywords=("vps",))
    rich = RoutableDomain(name="b", display_name="B", keywords=("vps", "evolution"))
    router = DomainRouter(domains=(only_shared, rich), default_domain="a")

    assert router.route("minha vps").show_menu is True
    assert router.route("a evolution travou").domain == "b"


def test_keyword_listed_twice_in_one_domain_is_not_shared() -> None:
    # Dedupe dentro do dominio: a mesma keyword repetida em um unico config nao
    # pode parecer "compartilhada" e se auto-anular.
    a = RoutableDomain(name="a", display_name="A", keywords=("vps", "vps", "rebuild"))
    b = RoutableDomain(name="b", display_name="B", keywords=("evolution",))
    router = DomainRouter(domains=(a, b), default_domain="a")

    assert "vps" not in router._shared_keywords()
    assert router.route("minha vps travou").domain == "a"


# --- transport integration with routing enabled -------------------------------


class _FakeDomainLoader:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def load(self, domain_name: str):
        self.loaded.append(domain_name)
        return DomainConfig(
            name=domain_name, display_name=domain_name, root_path=Path(".")
        )


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


def _transport(client, chat, loader, last_out_store=None):
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
        last_out_store=last_out_store,
    )


def _message(text: str) -> MetaInboundTextMessage:
    return MetaInboundTextMessage(
        message_id="wamid.inbound",
        from_wa_id="5511999999999",
        timestamp="1710000000",
        text=text,
    )


def test_transport_greeting_sends_natural_greeting_without_calling_engine() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(client, chat, loader)

    result = transport.handle_text_message(message=_message("Oi"), request_id="req")

    assert chat.called is False
    assert result.handoff_status == "routing_menu"
    assert "HostGator Brasil" in client.sent[0]
    assert "1)" not in client.sent[0]


def test_transport_second_ambiguous_turn_sends_clarification() -> None:
    client, chat, loader = _FakeClient(), _FakeChatService(), _FakeDomainLoader()
    transport = _transport(
        client, chat, loader, last_out_store=InMemorySessionDomainStore()
    )

    transport.handle_text_message(message=_message("Oi"), request_id="r1")
    transport.handle_text_message(
        message=_message("preciso de uma coisa"), request_id="r2"
    )

    assert chat.called is False
    assert "HostGator Brasil" in client.sent[0]
    assert client.sent[1] == transport.router.clarification_text()


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

    # reset -> clarification question (not the full greeting), engine not
    # called, binding cleared
    calls_before = chat.calls
    result = transport.handle_text_message(message=_message("menu"), request_id="r2")
    assert result.handoff_status == "routing_menu"
    assert client.sent[-1] == transport.router.clarification_text()
    assert chat.calls == calls_before
    assert store.get(session_key) is None

    # after reset, a generic message has no sticky domain -> fallback again
    result2 = transport.handle_text_message(
        message=_message("pode me explicar melhor?"),
        request_id="r3",
    )
    assert result2.handoff_status == "routing_menu"
