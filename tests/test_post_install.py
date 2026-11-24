"""Tests for the guided installation (scripts/post_install.py + deploy/install.sh).

The post-install steps run here with fakes for the database and the readiness
probe; the real flow runs in Docker as described in docs/runbooks/docker-install.md.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.domain_registry import UPSERT_DOMAIN_SQL
from scripts import post_install
from scripts.post_install import (
    EXIT_CONFIG,
    EXIT_EVALS_FAILED,
    EXIT_FAILED,
    EXIT_OK,
    render_markdown,
    run_post_install,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "deploy" / "install.sh"
PHONE = "+5511987654321"
IDENTITY_SECRET = "identity-" + "z" * 24


class _Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        self.db.executed.append((" ".join(str(query).split()), params))

    def fetchone(self):
        return ("00000000-0000-0000-0000-000000000001",)


class _Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return _Cursor(self.db)

    def commit(self):
        self.db.commits += 1

    def close(self):
        self.db.closed += 1


class _Database:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.executed: list[tuple[str, object]] = []
        self.commits = 0
        self.closed = 0

    def connect(self, _url):
        if self.fail:
            raise OSError("connection refused to postgresql://u:pw@db/x")
        return _Connection(self)


def _settings(tmp_domains=None, **overrides):
    values = dict(
        app_name="Acme Suporte",
        app_env="production",
        domains_path=tmp_domains or REPO_ROOT / "domains",
        database_url="postgresql://supportfaq:db-password-123@postgres:5432/supportfaq",
        identity_hash_secret=IDENTITY_SECRET,
        openai_api_key=None,
        anthropic_api_key=None,
        retrieval_backend="lexical",
        enable_public_chat_ui=False,
        enable_support_console=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _ready(_settings):
    return {"status": "ok", "components": {"database": {"status": "ok"}}}


def _unavailable(_settings):
    return {
        "status": "unavailable",
        "components": {"migrations": {"status": "unavailable", "pending_count": 1}},
    }


def _all_pass(_domain, suite):
    return SimpleNamespace(total=len(suite.cases), passed=len(suite.cases))


def _run(settings=None, *, db=None, readiness=_ready, run_eval=_all_pass, **kwargs):
    db = db or _Database()
    report = run_post_install(
        settings or _settings(),
        connect=db.connect,
        readiness=readiness,
        run_eval=run_eval,
        **kwargs,
    )
    return report, db


def _step(report, name):
    return [step for step in report.steps if step.name == name]


# --- domains ------------------------------------------------------------------------


def test_registers_every_domain_of_the_pack_without_embeddings() -> None:
    report, db = _run(skip_evals=True)

    upserts = [params for query, params in db.executed if "INSERT INTO domains" in query]
    names = sorted(name for name, _display in upserts)
    assert names == sorted(name for name, _ in report.domains)
    assert "suporte-vps-whatsapp" in names
    assert db.commits == 1 and db.closed == 1
    assert _step(report, "register_domains")[0].status == "ok"
    assert report.exit_code == EXIT_OK


def test_domain_upsert_sql_is_shared_with_pgvector_ingestion() -> None:
    source = (REPO_ROOT / "app" / "ingestion" / "pgvector_writer.py").read_text(encoding="utf-8")

    assert "upsert_domain(cursor" in source
    assert "INSERT INTO domains" not in source
    assert "ON CONFLICT (name) DO UPDATE" in UPSERT_DOMAIN_SQL


def test_database_failure_is_reported_without_leaking_the_url() -> None:
    report, _db = _run(db=_Database(fail=True), skip_evals=True)
    markdown = render_markdown(report)

    assert _step(report, "register_domains")[0].status == "failed"
    assert report.exit_code == EXIT_FAILED
    assert "db-password-123" not in markdown and "pw@db" not in markdown


def test_unready_stack_skips_database_steps_and_fails() -> None:
    report, db = _run(readiness=_unavailable, skip_evals=True)

    assert db.executed == []
    assert _step(report, "readiness")[0].status == "failed"
    assert _step(report, "register_domains")[0].status == "skipped"
    assert report.exit_code == EXIT_FAILED


def test_empty_pack_fails(tmp_path) -> None:
    report, _db = _run(_settings(tmp_domains=tmp_path), skip_evals=True)

    assert _step(report, "domains")[0].status == "failed"
    assert report.exit_code == EXIT_FAILED


# --- admin --------------------------------------------------------------------------


def test_admin_is_registered_and_only_last4_is_reported() -> None:
    report, db = _run(admin_phone=PHONE, admin_name="Maria", skip_evals=True)
    markdown = render_markdown(report)

    staff = [params for query, params in db.executed if "INSERT INTO staff_members" in query]
    assert len(staff) == 1
    phone_hash, last4, name = staff[0]
    assert (last4, name) == ("4321", "Maria")
    assert PHONE not in phone_hash and len(phone_hash) >= 32
    assert "Maria (****4321)" in markdown
    assert PHONE not in markdown and "987654321" not in markdown
    assert IDENTITY_SECRET not in markdown


def test_admin_requires_identity_secret() -> None:
    report, db = _run(
        _settings(identity_hash_secret=None),
        admin_phone=PHONE,
        admin_name="Maria",
        skip_evals=True,
    )

    assert _step(report, "admin")[0].status == "failed"
    assert not any("staff_members" in query for query, _ in db.executed)
    assert report.exit_code == EXIT_FAILED


def test_invalid_admin_phone_fails_without_echoing_it() -> None:
    report, _db = _run(admin_phone="12345-abc", admin_name="Maria", skip_evals=True)
    markdown = render_markdown(report)

    assert _step(report, "admin")[0].status == "failed"
    assert "E.164" in markdown and "12345-abc" not in markdown


def test_admin_with_console_off_suggests_enabling_it() -> None:
    report, _db = _run(admin_phone=PHONE, admin_name="Maria", skip_evals=True)

    assert any("ENABLE_SUPPORT_CONSOLE" in item for item in report.next_steps)


# --- evals --------------------------------------------------------------------------


def test_runs_the_confinement_suites_that_exist_per_domain() -> None:
    seen = []

    def record(domain, suite):
        seen.append(domain.name)
        return _all_pass(domain, suite)

    report, _db = _run(run_eval=record)

    suites = {(summary.domain, summary.suite) for summary in report.evals}
    assert ("suporte-vps-whatsapp", "evals/confinement/secrets.yaml") in suites
    assert ("suporte-vps-whatsapp", "evals/cases.yaml") in suites
    # pgvector_* e intake nao entram: dependem de chave/embedding ou sao outro fluxo.
    assert all(suite.startswith("evals/cases") or "/confinement/" in suite for _, suite in suites)
    assert set(seen) == {name for name, _ in report.domains}
    assert _step(report, "evals")[-1].status == "ok"


def test_failing_eval_marks_attention_and_exit_code_3() -> None:
    def fail_vendas_cases(domain, suite):
        if domain.name == "vendas":
            return SimpleNamespace(total=len(suite.cases), passed=len(suite.cases) - 1)
        return _all_pass(domain, suite)

    report, _db = _run(run_eval=fail_vendas_cases)

    assert report.exit_code == EXIT_EVALS_FAILED
    assert _step(report, "evals")[-1].status == "attention"
    assert any("evals com falha" in item for item in report.next_steps)
    assert "⚠️ instalada, com evals falhando" in render_markdown(report)


def test_real_confinement_evals_pass_for_the_default_domain() -> None:
    settings = _settings()
    report, _db = _run(settings, run_eval=post_install._run_eval_suite)

    default = [s for s in report.evals if s.domain == "suporte-vps-whatsapp"]
    assert default and all(summary.failed == 0 for summary in default)


# --- report e main ------------------------------------------------------------------


def test_report_has_no_secret_values() -> None:
    report, _db = _run(admin_phone=PHONE, admin_name="Maria")
    markdown = render_markdown(report)

    for secret in ("db-password-123", IDENTITY_SECRET, PHONE, "postgresql://"):
        assert secret not in markdown
    assert markdown.startswith("# Relatorio de instalacao - Acme Suporte")


def test_report_lists_next_steps_for_a_minimal_install() -> None:
    report, _db = _run(skip_evals=True)

    joined = " ".join(report.next_steps)
    assert "OPENAI_API_KEY" in joined
    assert "RETRIEVAL_BACKEND=pgvector" in joined
    assert "ENABLE_PUBLIC_CHAT_UI" in joined


def test_main_requires_admin_phone_and_name_together(capsys) -> None:
    assert post_install.main(["--admin-phone", PHONE]) == EXIT_CONFIG
    assert capsys.readouterr().out == ""


def test_main_keeps_stdout_for_the_report_only(monkeypatch, capsys) -> None:
    def noisy(settings, **_kwargs):
        print("noise from a step")
        report = post_install.InstallReport(app_name="x", app_env="production", generated_at="now")
        report.add("readiness", "ok", "ok")
        return report

    monkeypatch.setattr(post_install, "run_post_install", noisy)

    assert post_install.main([]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.startswith("# Relatorio de instalacao")
    assert "noise from a step" in captured.err and "noise" not in captured.out


# --- deploy/install.sh --------------------------------------------------------------


def test_install_script_never_overwrites_env_or_deletes_data() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "if [ -e .env ]; then" in text
    assert "down" not in text and "volume rm" not in text and "rm -rf" not in text
    assert "umask 077" in text and "chmod 600 .env" in text


def test_install_script_generates_every_secret_of_the_env_example() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    example = (REPO_ROOT / "deploy" / "production.env.example").read_text(encoding="utf-8")
    placeholders = {
        line.split("=", 1)[0]
        for line in example.splitlines()
        if not line.startswith("#") and "<set-private-value>" in line
    }

    for name in placeholders:
        assert f"s|^{name}=" in text, f"install.sh does not generate {name}"
    assert "fill every <set-private-value>" in text


def test_smoke_script_generates_every_secret_of_the_env_example() -> None:
    text = (REPO_ROOT / "deploy" / "docker-smoke.sh").read_text(encoding="utf-8")

    assert 's|^IDENTITY_HASH_SECRET=' in text


def test_install_script_never_prints_the_api_key() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert "echo \"$API_KEY\"" not in text and "log \"$API_KEY" not in text
    assert "unset API_KEY" in text
    assert "> \"$REPORT_TMP\"" in text  # o relatorio sai do stdout do post_install


def test_install_script_keeps_lf_endings() -> None:
    assert b"\r\n" not in INSTALL_SH.read_bytes()


@pytest.mark.parametrize("flag", ["--admin-phone", "--admin-name", "--skip-evals", "--client-pack", "--report"])
def test_install_script_documents_its_flags(flag) -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    header = text.split("set -euo pipefail")[0]

    assert flag in header


def test_install_errors_print_only_the_message() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    # "$*" incluiria o codigo de saida na mensagem de erro.
    assert 'die() { echo "init: ERROR $1" >&2; exit "${2:-1}"; }' in text


def test_install_reports_stay_out_of_git() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "install-report.md" in ignored
