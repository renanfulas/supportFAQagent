from pathlib import Path

from app.domain_engine.loader import DomainLoader


def write_domain_config(root: Path, name: str, content: str) -> None:
    domain_path = root / name
    domain_path.mkdir(parents=True)
    (domain_path / "domain.yaml").write_text(content, encoding="utf-8")


def test_loader_loads_valid_domain_contract(tmp_path: Path) -> None:
    write_domain_config(
        tmp_path,
        "vendas",
        """
contract_version: 1
name: vendas
display_name: Suporte de Vendas
description: Dominio de vendas.
owner: Comercial
behavior:
  persona: consultor de vendas
  primary_goal: ajudar leads com duvidas comerciais
  answer_guidelines:
    - qualifique antes de sugerir plano
  out_of_scope:
    - suporte tecnico profundo
knowledge:
  sources:
    - knowledge/faqs
""",
    )

    domain = DomainLoader(tmp_path).load("vendas")

    assert domain is not None
    assert domain.name == "vendas"
    assert domain.behavior.persona == "consultor de vendas"
    assert domain.knowledge.sources == ["knowledge/faqs"]


def test_loader_rejects_domain_when_folder_and_config_name_diverge(
    tmp_path: Path,
) -> None:
    write_domain_config(
        tmp_path,
        "vendas",
        """
name: suporte
display_name: Suporte
""",
    )

    assert DomainLoader(tmp_path).load("vendas") is None


def test_feature_flags_default_to_empty_and_off(tmp_path: Path) -> None:
    write_domain_config(
        tmp_path,
        "vendas",
        """
name: vendas
display_name: Suporte de Vendas
""",
    )

    domain = DomainLoader(tmp_path).load("vendas")

    assert domain is not None
    assert domain.feature_flags == {}
    # Unknown flags are safely off, so behavior is unchanged until a domain opts in.
    assert domain.is_flag_enabled("context_aware_scope") is False


def test_feature_flags_load_from_contract(tmp_path: Path) -> None:
    write_domain_config(
        tmp_path,
        "vendas",
        """
name: vendas
display_name: Suporte de Vendas
feature_flags:
  context_aware_scope: true
  soft_low_confidence: false
""",
    )

    domain = DomainLoader(tmp_path).load("vendas")

    assert domain is not None
    assert domain.is_flag_enabled("context_aware_scope") is True
    assert domain.is_flag_enabled("soft_low_confidence") is False
    assert domain.is_flag_enabled("not_declared") is False


def test_list_domains_returns_only_valid_contracts(tmp_path: Path) -> None:
    write_domain_config(
        tmp_path,
        "vendas",
        """
name: vendas
display_name: Suporte de Vendas
""",
    )
    write_domain_config(
        tmp_path,
        "quebrado",
        """
llm:
  provider: openai
""",
    )

    assert DomainLoader(tmp_path).list_domains() == ["vendas"]
