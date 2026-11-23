import html
import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.chat_ui import load_chat_ui_template, render_chat_ui_page
from app.core.config import Settings, get_settings
from app.domain_engine.installation import (
    InstallationChatUIConfig,
    InstallationConfig,
    load_installation_config,
)
from app.domain_engine.loader import DomainLoader
from app.main import CHAT_STATIC_DIR, create_app
from app.orchestration.channel_routing import build_domain_router


# Golden copy: the exact texts the core used to hardcode for HostGator. The
# client pack (domains/installation.yaml) must reproduce them character for
# character so moving them out of the core changes nothing in production.
HOSTGATOR_GREETING = (
    "Olá! Somos a HostGator Brasil, provedora de hospedagem de sites e servidores.\n\n"
    "Sou o assistente virtual e posso te ajudar com suporte técnico ou com nossos "
    "planos de hospedagem e VPS. Se precisar, também te encaminho para um "
    "atendente humano.\n\n"
    "Como posso te ajudar?"
)
HOSTGATOR_CLARIFICATION = (
    "Você já é cliente e precisa de suporte técnico, ou quer conhecer nossos "
    "planos de hospedagem e VPS?"
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_domain(root: Path, name: str, display_name: str, keywords: list[str]) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    keyword_lines = "\n".join(f"    - {keyword}" for keyword in keywords)
    (folder / "domain.yaml").write_text(
        f"name: {name}\ndisplay_name: {display_name}\nrouting:\n  keywords:\n{keyword_lines}\n",
        encoding="utf-8",
    )


def _two_domain_pack(root: Path) -> None:
    _write_domain(root, "acme-suporte", "Suporte Acme", ["erro", "acesso"])
    _write_domain(root, "acme-vendas", "Vendas Acme", ["plano", "preco"])


def _router_settings(domains_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="development",
        DOMAINS_PATH=str(domains_path),
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="acme-suporte,acme-vendas",
        DEFAULT_DOMAIN="acme-suporte",
    )


# --- loader --------------------------------------------------------------------


def test_missing_installation_file_returns_neutral_defaults(tmp_path: Path) -> None:
    config = load_installation_config(tmp_path)

    assert config == InstallationConfig()
    assert config.brand.name is None
    assert config.routing.greeting is None
    assert config.chat_ui.quick_prompts == []


@pytest.mark.parametrize(
    "content",
    [
        "brand: [isto nao e um mapa",  # YAML invalido
        "- lista\n- no topo\n",  # nao e mapa
        "contract_version: 2\n",  # versao nao suportada
        "brand:\n  nome_errado: Acme\n",  # chave desconhecida (extra=forbid)
    ],
)
def test_invalid_installation_file_falls_back_without_raising(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "installation.yaml").write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        config = load_installation_config(tmp_path)

    assert config == InstallationConfig()
    assert "installation_config_invalid" in caplog.text
    # The file content is never logged.
    assert "Acme" not in caplog.text
    assert "lista" not in caplog.text


def test_repo_installation_reproduces_hostgator_copy_exactly() -> None:
    config = load_installation_config(REPO_ROOT / "domains")

    assert config.brand.name == "HostGator Brasil"
    assert config.routing.greeting == HOSTGATOR_GREETING
    assert config.routing.clarification == HOSTGATOR_CLARIFICATION
    assert config.chat_ui.kicker == "HostGator support flow"
    assert [prompt.id for prompt in config.chat_ui.quick_prompts] == [
        "iniciante-primeiros-passos",
        "qrcode-whatsapp",
        "risco-bloqueio-whatsapp",
        "webhook-n8n-zapi",
    ]


def test_installation_file_is_not_loaded_as_a_domain() -> None:
    names = DomainLoader(REPO_ROOT / "domains").list_domains()

    assert "installation" not in names
    assert "installation.yaml" not in names


# --- router wiring -------------------------------------------------------------


def test_router_uses_installation_copy(tmp_path: Path) -> None:
    _two_domain_pack(tmp_path)
    (tmp_path / "installation.yaml").write_text(
        "brand:\n  name: Acme\nrouting:\n  greeting: Bem-vindo à Acme!\n"
        "  clarification: Suporte ou vendas?\n",
        encoding="utf-8",
    )

    router = build_domain_router(_router_settings(tmp_path), DomainLoader(tmp_path))

    assert router is not None
    assert router.greeting_text() == "Bem-vindo à Acme!"
    assert router.clarification_text() == "Suporte ou vendas?"


def test_router_without_installation_is_brand_neutral(tmp_path: Path) -> None:
    _two_domain_pack(tmp_path)

    router = build_domain_router(_router_settings(tmp_path), DomainLoader(tmp_path))

    assert router is not None
    greeting = router.greeting_text()
    assert "Suporte Acme ou Vendas Acme" in greeting
    assert "HostGator" not in greeting
    assert "HostGator" not in router.clarification_text()


def test_router_with_only_brand_name_builds_neutral_greeting_with_it(tmp_path: Path) -> None:
    _two_domain_pack(tmp_path)
    (tmp_path / "installation.yaml").write_text("brand:\n  name: Acme\n", encoding="utf-8")

    router = build_domain_router(_router_settings(tmp_path), DomainLoader(tmp_path))

    assert router is not None
    assert "assistente virtual de Acme" in router.greeting_text()


def test_repo_router_keeps_hostgator_greeting_unchanged() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        DOMAINS_PATH=str(REPO_ROOT / "domains"),
        ENABLE_WHATSAPP_DOMAIN_ROUTER="true",
        WHATSAPP_ROUTER_DOMAINS="suporte-vps-whatsapp,vendas",
    )

    router = build_domain_router(settings, DomainLoader(REPO_ROOT / "domains"))

    assert router is not None
    assert router.greeting_text() == HOSTGATOR_GREETING
    assert router.clarification_text() == HOSTGATOR_CLARIFICATION


# --- chat UI rendering ---------------------------------------------------------


def test_rendered_page_has_no_unreplaced_placeholders() -> None:
    page = render_chat_ui_page(load_chat_ui_template(CHAT_STATIC_DIR), InstallationChatUIConfig())

    assert re.search(r"\{\{\w+\}\}", page) is None
    assert "HostGator" not in page


def test_rendered_page_escapes_text_and_json_block() -> None:
    hostile = '<script>alert(1)</script> & "x"'
    config = InstallationChatUIConfig(
        heading=hostile,
        quick_prompts=[{"id": "p1", "title": "</script><b>x</b>", "message": "oi"}],
    )

    page = render_chat_ui_page(load_chat_ui_template(CHAT_STATIC_DIR), config)

    assert "<script>alert(1)</script>" not in page
    assert html.escape(hostile, quote=True) in page
    # Only the template's own two script tags close; no value closes the block.
    assert page.count("</script>") == 2
    block = re.search(
        r'<script id="chat-config" type="application/json">(.*?)</script>', page, re.S
    )
    assert block is not None
    data = json.loads(block.group(1))
    assert data["quick_prompts"][0]["title"] == "</script><b>x</b>"


def test_chat_ui_route_without_installation_is_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_domain_pack(tmp_path)
    monkeypatch.setenv("DOMAINS_PATH", str(tmp_path))
    get_settings.cache_clear()
    try:
        response = TestClient(create_app()).get("/chat-ui")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert "HostGator" not in response.text
    assert "VPS" not in response.text
    assert '"quick_prompts": []' in response.text


def test_chat_ui_route_uses_repo_installation_copy() -> None:
    response = TestClient(create_app()).get("/chat-ui")

    assert response.status_code == 200
    text = html.unescape(response.text)
    assert "<title>Suporte VPS & WhatsApp</title>" in text
    assert "HostGator support flow" in text
    assert "qrcode-whatsapp" in text
