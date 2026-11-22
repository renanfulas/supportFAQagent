from pathlib import Path

import pytest
import yaml

from app.domain_engine import scaffold
from app.domain_engine.loader import DomainLoader
from app.domain_engine.scaffold import (
    EVAL_FILES,
    DomainScaffoldSpec,
    ScaffoldError,
    create_domain,
    render_domain_files,
    validate_domain_name,
)
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner
from scripts import new_domain


def make_spec(**overrides: str) -> DomainScaffoldSpec:
    values = {
        "name": "acme-suporte",
        "display_name": "Acme Suporte",
        "owner": "Time Acme",
        "description": "",
    }
    values.update(overrides)
    return DomainScaffoldSpec(**values)


@pytest.mark.parametrize("name", ["acme", "acme-suporte", "cliente-2-vendas", "abc"])
def test_validate_domain_name_accepts_kebab_case(name: str) -> None:
    assert validate_domain_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["ab", "Acme", "acme_suporte", "-acme", "acme-", "acme--suporte", "acme suporte", "a" * 65, "../x"],
)
def test_validate_domain_name_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ScaffoldError):
        validate_domain_name(name)


@pytest.mark.parametrize("field", ["display_name", "owner"])
def test_render_requires_display_name_and_owner(field: str) -> None:
    with pytest.raises(ScaffoldError):
        render_domain_files(make_spec(**{field: "  "}))


def test_create_domain_writes_a_loadable_domain(tmp_path: Path) -> None:
    target = create_domain(make_spec(), tmp_path)

    assert target == tmp_path / "acme-suporte"
    for relative in render_domain_files(make_spec()):
        assert (target / relative).exists(), relative

    domain = DomainLoader(tmp_path).load("acme-suporte")
    assert domain is not None
    assert domain.display_name == "Acme Suporte"
    assert domain.owner == "Time Acme"
    assert domain.llm.provider == "mock"
    assert domain.checkout.enabled is False
    assert domain.feature_flags == {}
    assert "acme-suporte" in DomainLoader(tmp_path).list_domains()


def test_user_supplied_text_is_quoted_safely(tmp_path: Path) -> None:
    tricky = 'Acme: Suporte "VIP" # Ação'
    create_domain(make_spec(display_name=tricky, description="linha: com dois pontos"), tmp_path)

    raw = yaml.safe_load((tmp_path / "acme-suporte" / "domain.yaml").read_text(encoding="utf-8"))

    assert raw["display_name"] == tricky
    assert raw["description"] == "linha: com dois pontos"


def test_create_domain_never_overwrites_an_existing_folder(tmp_path: Path) -> None:
    existing = tmp_path / "acme-suporte"
    existing.mkdir()
    (existing / "domain.yaml").write_text("keep: me\n", encoding="utf-8")

    with pytest.raises(ScaffoldError):
        create_domain(make_spec(), tmp_path)

    assert (existing / "domain.yaml").read_text(encoding="utf-8") == "keep: me\n"


def test_invalid_render_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_render(spec: DomainScaffoldSpec) -> dict[str, str]:
        files = render_domain_files(spec)
        files["domain.yaml"] = "name: outro-nome\n"
        return files

    monkeypatch.setattr(scaffold, "render_domain_files", broken_render)

    with pytest.raises(ScaffoldError):
        scaffold.create_domain(make_spec(), tmp_path)

    assert not (tmp_path / "acme-suporte").exists()


def test_knowledge_folders_start_without_ingestible_documents(tmp_path: Path) -> None:
    target = create_domain(make_spec(), tmp_path)

    ingestible = [
        path
        for path in (target / "knowledge").rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}
    ]

    assert ingestible == []


def test_scaffold_is_generic_and_carries_no_existing_client_content() -> None:
    contents = "\n".join(render_domain_files(make_spec()).values()).lower()

    assert "hostgator" not in contents
    assert "vps" not in contents


def test_every_confinement_suite_has_accented_mirrors(tmp_path: Path) -> None:
    target = create_domain(make_spec(), tmp_path)
    loader = EvalSuiteLoader()

    for relative in EVAL_FILES:
        suite = loader.load(target / relative)
        assert suite is not None, relative
        ids = {case.id for case in suite.cases}
        for case_id in ids:
            if not case_id.endswith("-acentuado"):
                assert f"{case_id}-acentuado" in ids, f"{relative}: {case_id}"


def test_generated_eval_suites_pass_out_of_the_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.retrieval.service.get_settings",
        lambda: type("Settings", (), {"retrieval_backend": "lexical"})(),
    )
    create_domain(make_spec(), tmp_path)
    domain = DomainLoader(tmp_path).load("acme-suporte")
    assert domain is not None
    runner = DomainEvalRunner()

    for relative in EVAL_FILES:
        suite = EvalSuiteLoader().load(domain.root_path / relative)
        assert suite is not None
        result = runner.run(domain=domain, suite=suite)
        failures = [(r.case_id, r.failures, r.handoff_reasons) for r in result.results if not r.passed]
        assert failures == [], relative


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = new_domain.main(
        [
            "acme-suporte",
            "--display-name",
            "Acme Suporte",
            "--owner",
            "Time Acme",
            "--domains-path",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert code == 0
    assert "domain.yaml" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_cli_creates_domain_and_refuses_a_second_run(tmp_path: Path) -> None:
    argv = [
        "acme-suporte",
        "--display-name",
        "Acme Suporte",
        "--owner",
        "Time Acme",
        "--domains-path",
        str(tmp_path),
    ]

    assert new_domain.main(argv) == 0
    assert (tmp_path / "acme-suporte" / "domain.yaml").exists()
    assert new_domain.main(argv) == 1


def test_cli_rejects_invalid_name(tmp_path: Path) -> None:
    code = new_domain.main(
        ["Acme_Suporte", "--display-name", "x", "--owner", "y", "--domains-path", str(tmp_path)]
    )

    assert code == 1
    assert list(tmp_path.iterdir()) == []
