"""Tests for the configuration profiles and `python -m scripts.config_validate`.

The validator must explain every problem by variable name and never print a
value; the profile templates must stay installable and in sync with each other.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import io
import re
import secrets
from pathlib import Path

import pytest

from app.core.config import Settings
from scripts import config_validate
from scripts.config_validate import (
    ERROR,
    EXIT_INVALID,
    EXIT_OK,
    EXIT_UNREADABLE,
    INFO,
    PRIVATE_PLACEHOLDER,
    PROFILE_FLAGS,
    PROVIDER_PLACEHOLDER,
    TOOL_VARS,
    WARNING,
    parse_env_text,
    render,
    validate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "domains"
INSTALL_SH = REPO_ROOT / "deploy" / "install.sh"
SMOKE_SH = REPO_ROOT / "deploy" / "docker-smoke.sh"
TEMPLATES = {
    "minimo": REPO_ROOT / "deploy" / "production.env.example",
    "padrao": REPO_ROOT / "deploy" / "profiles" / "padrao.env.example",
    "completo": REPO_ROOT / "deploy" / "profiles" / "completo.env.example",
}
# Keys a richer profile may set differently from the minimo template.
PROFILE_OVERRIDES = {"CONFIG_PROFILE", "COMPOSE_PROFILES", "OPENAI_API_KEY", "SESSION_STATE_BACKEND"}


def _template(profile: str) -> dict[str, str]:
    values, _duplicates = parse_env_text(TEMPLATES[profile].read_text(encoding="utf-8"))
    return values


def _filled(profile: str) -> dict[str, str]:
    """The template as install.sh leaves it, plus the provider values a person pastes."""
    values = _template(profile)
    for name, value in values.items():
        if PRIVATE_PLACEHOLDER in value and name != "DATABASE_URL":
            values[name] = secrets.token_hex(24)
        elif PROVIDER_PLACEHOLDER in value:
            values[name] = f"provider-{name.lower()}-{secrets.token_hex(8)}"
    values["DATABASE_URL"] = f"postgresql://supportfaq:{values['POSTGRES_PASSWORD']}@postgres:5432/supportfaq"
    return values


def _run(values: dict[str, str], **kwargs):
    kwargs.setdefault("pack_dir", PACK)
    return validate(values, **kwargs)


def _messages(result, level: str | None = None) -> list[str]:
    return [
        f"{finding.name}: {finding.message}"
        for finding in result.findings
        if level is None or finding.level == level
    ]


def _has(result, level: str, name: str, fragment: str = "") -> bool:
    return any(
        finding.level == level and finding.name == name and fragment in finding.message
        for finding in result.findings
    )


# --- profile templates ------------------------------------------------------------


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_filled_profile_is_valid(profile) -> None:
    result = _run(_filled(profile))

    assert _messages(result, ERROR) == []
    assert result.exit_code() == EXIT_OK
    assert result.profile == profile
    assert "suporte-vps-whatsapp" in result.domains


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_unfilled_profile_names_every_placeholder(profile) -> None:
    template = _template(profile)
    pending = {
        name
        for name, value in template.items()
        if PRIVATE_PLACEHOLDER in value or PROVIDER_PLACEHOLDER in value
    }

    result = _run(template)

    flagged = {finding.name for finding in result.findings if "ainda tem <set-" in finding.message}
    assert flagged == pending
    assert result.exit_code() == EXIT_INVALID
    # Placeholders are reported once; the Settings build does not add noise.
    assert not any("must be different" in message for message in _messages(result))


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_profile_uses_only_known_variables(profile) -> None:
    known = {field.alias for field in Settings.model_fields.values() if field.alias} | TOOL_VARS

    assert set(_template(profile)) - known == set()


@pytest.mark.parametrize("profile", ["padrao", "completo"])
def test_richer_profiles_keep_the_minimo_base(profile) -> None:
    base = _template("minimo")
    richer = _template(profile)

    for name, value in base.items():
        assert name in richer, f"{profile} lost {name}"
        if name not in PROFILE_OVERRIDES:
            assert richer[name] == value, f"{profile} changed {name}"


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_profile_declares_itself_and_turns_on_its_flags(profile) -> None:
    values = _template(profile)

    assert values["CONFIG_PROFILE"] == profile
    for flag in PROFILE_FLAGS[profile]:
        assert values.get(flag) == "true", f"{profile} must turn on {flag}"


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_install_generates_every_private_value_of_the_profile(profile) -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    for name, value in _template(profile).items():
        if PRIVATE_PLACEHOLDER in value:
            assert f"s|^{name}=" in text, f"install.sh does not generate {name}"


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_provider_values_are_never_generated(profile) -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    for name, value in _template(profile).items():
        if PROVIDER_PLACEHOLDER in value:
            assert f"s|^{name}=" not in text, f"install.sh must not invent {name}"


@pytest.mark.parametrize("profile", sorted(TEMPLATES))
def test_profile_templates_keep_lf_endings(profile) -> None:
    assert b"\r\n" not in TEMPLATES[profile].read_bytes()


def test_profile_templates_are_pinned_to_lf() -> None:
    rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "deploy/profiles/*.env.example text eol=lf" in rules


# --- rules ------------------------------------------------------------------------


def test_database_password_must_match_the_embedded_postgres() -> None:
    values = _filled("minimo")
    values["POSTGRES_PASSWORD"] = secrets.token_hex(24)

    result = _run(values)

    assert _has(result, ERROR, "DATABASE_URL", "POSTGRES_PASSWORD")


def test_database_user_and_name_must_match_the_embedded_postgres() -> None:
    values = _filled("minimo")
    values["DATABASE_URL"] = values["DATABASE_URL"].replace("supportfaq:", "outro:").replace(
        "/supportfaq", "/outro"
    )

    result = _run(values)

    assert _has(result, ERROR, "DATABASE_URL", "POSTGRES_USER")
    assert _has(result, ERROR, "DATABASE_URL", "POSTGRES_DB")


def test_embedded_database_host_needs_the_db_compose_profile() -> None:
    values = _filled("minimo")
    values["COMPOSE_PROFILES"] = ""

    assert _has(_run(values), ERROR, "DATABASE_URL", 'perfil "db"')


def test_external_database_with_embedded_postgres_is_a_warning() -> None:
    values = _filled("minimo")
    values["DATABASE_URL"] = "postgresql://app:" + secrets.token_hex(24) + "@db.example.internal:5432/app"

    result = _run(values)

    assert _has(result, WARNING, "COMPOSE_PROFILES", "outro banco")
    assert _messages(result, ERROR) == []


def test_redis_service_needs_the_redis_compose_profile() -> None:
    values = _filled("completo")
    values["COMPOSE_PROFILES"] = "db"

    assert _has(_run(values), ERROR, "SESSION_STATE_REDIS_URL", 'perfil "redis"')


def test_richer_profile_requires_an_llm_key() -> None:
    values = _filled("padrao")
    values["OPENAI_API_KEY"] = ""

    result = _run(values)

    assert _has(result, ERROR, "OPENAI_API_KEY", "chave de LLM")


def test_anthropic_key_satisfies_the_llm_requirement() -> None:
    values = _filled("padrao")
    values["OPENAI_API_KEY"] = ""
    values["ANTHROPIC_API_KEY"] = "provider-" + secrets.token_hex(8)

    assert _messages(_run(values), ERROR) == []


def test_minimo_without_llm_key_is_only_informed() -> None:
    result = _run(_filled("minimo"))

    assert _has(result, INFO, "OPENAI_API_KEY", "fallback")


def test_pgvector_needs_openai_embeddings_and_warns_about_readiness() -> None:
    values = _filled("minimo")
    values["RETRIEVAL_BACKEND"] = "pgvector"

    result = _run(values)

    assert _has(result, ERROR, "RETRIEVAL_BACKEND", "OPENAI_API_KEY")
    assert _has(result, WARNING, "RETRIEVAL_BACKEND", "ingeridos")


def test_console_with_memory_otp_delivery_is_an_error_in_production() -> None:
    values = _filled("completo")
    values["WEB_AUTH_OTP_DELIVERY_TRANSPORT"] = "memory"

    assert _has(_run(values), ERROR, "WEB_AUTH_OTP_DELIVERY_TRANSPORT", "nunca chega")


def test_reused_and_short_secrets_are_errors() -> None:
    values = _filled("completo")
    values["OTP_DIGEST_SECRET"] = values["IDENTITY_HASH_SECRET"]
    values["API_SECRET_KEY"] = "curta"

    result = _run(values)

    assert _has(result, ERROR, "IDENTITY_HASH_SECRET", "OTP_DIGEST_SECRET")
    assert _has(result, ERROR, "API_SECRET_KEY", "segredo curto")


def test_installation_profile_refuses_a_development_env() -> None:
    values = _filled("minimo")
    values["APP_ENV"] = "development"

    assert _has(_run(values), ERROR, "APP_ENV", "production")


def test_profile_flag_turned_off_is_a_warning() -> None:
    values = _filled("padrao")
    values["ENABLE_PUBLIC_CHAT_UI"] = "false"

    result = _run(values)

    assert _has(result, WARNING, "ENABLE_PUBLIC_CHAT_UI", "desligado")
    assert result.exit_code() == EXIT_OK
    assert result.exit_code(strict=True) == EXIT_INVALID


def test_unknown_variable_suggests_the_close_name() -> None:
    values = _filled("minimo")
    values["ENABLE_SUPORT_CONSOLE"] = "true"

    result = _run(values)

    assert _has(result, WARNING, "ENABLE_SUPORT_CONSOLE", "quis dizer ENABLE_SUPPORT_CONSOLE?")


def test_repeated_variable_is_a_warning() -> None:
    text = TEMPLATES["minimo"].read_text(encoding="utf-8") + "\nAPP_NAME=Outro\n"
    _values, duplicates = parse_env_text(text)

    result = _run(_filled("minimo"), duplicates=duplicates)

    assert _has(result, WARNING, "APP_NAME", "2 vezes")


def test_default_domain_must_exist_in_the_pack(tmp_path) -> None:
    values = _filled("minimo")
    values["DEFAULT_DOMAIN"] = "nao-existe"

    assert _has(_run(values), ERROR, "DEFAULT_DOMAIN", "nao existe")
    assert _has(_run(_filled("minimo"), pack_dir=tmp_path / "vazio"), ERROR, "CLIENT_PACK_DIR", "nao encontrada")
    assert _has(_run(_filled("minimo"), pack_dir=tmp_path), ERROR, "CLIENT_PACK_DIR", "nenhum dominio")


def test_router_domains_must_exist_in_the_pack() -> None:
    values = _filled("minimo")
    values["ENABLE_WEB_DOMAIN_ROUTER"] = "true"
    values["WHATSAPP_ROUTER_DOMAINS"] = "suporte-vps-whatsapp,nao-existe"

    assert _has(_run(values), ERROR, "WHATSAPP_ROUTER_DOMAINS", "1 dominio")


def test_tool_values_are_checked() -> None:
    values = _filled("minimo")
    values["STARTUP_MIGRATIONS"] = "sempre"
    values["STARTUP_READINESS_TIMEOUT_SECONDS"] = "-1"
    values["APP_PORT"] = "porta"

    result = _run(values)

    for name in ("STARTUP_MIGRATIONS", "STARTUP_READINESS_TIMEOUT_SECONDS", "APP_PORT"):
        assert _has(result, ERROR, name), name


def test_settings_catches_what_the_rules_do_not() -> None:
    values = _filled("minimo")
    values["ENABLE_HANDOFF_CONSENT_GATE"] = "true"

    result = _run(values)

    assert any(
        "o app recusaria iniciar" in message and "ENABLE_WEB_WHATSAPP_AUTH" in message
        for message in _messages(result, ERROR)
    )


def test_settings_check_ignores_the_process_environment(monkeypatch) -> None:
    # The file is what gets validated, not whatever the shell happens to export.
    monkeypatch.setenv("ENABLE_HANDOFF_CONSENT_GATE", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "not-a-number")

    assert _messages(_run(_filled("minimo")), ERROR) == []


# --- never print values -----------------------------------------------------------


def test_output_never_contains_values() -> None:
    values = _filled("completo")
    values["POSTGRES_PASSWORD"] = secrets.token_hex(24)  # forces a DATABASE_URL finding
    values["ENABLE_SUPPORT_INBOX"] = "talvez-" + secrets.token_hex(12)  # forces a Settings error
    values["ENABLE_SUPORT_CONSOLE"] = "valor-" + secrets.token_hex(12)

    result = _run(values)
    output = render(result, source=".env")

    assert result.exit_code() == EXIT_INVALID
    assert any("ENABLE_SUPPORT_INBOX" in message for message in _messages(result, ERROR))
    for name, value in values.items():
        if len(value) >= 12 and name not in {"SUPPORT_CONSOLE_TIMEZONE", "SESSION_STATE_REDIS_URL"}:
            assert value not in output, f"value of {name} leaked"


# --- main -------------------------------------------------------------------------


def _env_text(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


def test_main_reads_the_env_file(tmp_path, capsys) -> None:
    env = tmp_path / ".env"
    env.write_text(_env_text(_filled("minimo")), encoding="utf-8")

    code = config_validate.main(["--env-file", str(env), "--domains-path", str(PACK)])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("config validate:") and "perfil minimo" in out
    assert "resultado: 0 erro(s)" in out


def test_main_reads_stdin_for_the_container(capsys) -> None:
    stdin = io.StringIO(_env_text(_filled("padrao")))

    code = config_validate.main(["--env-file", "-", "--domains-path", str(PACK)], stdin=stdin)

    assert code == EXIT_OK
    assert "entrada padrao, perfil padrao" in capsys.readouterr().out


def test_main_profile_flag_overrides_the_file(tmp_path, capsys) -> None:
    env = tmp_path / ".env"
    env.write_text(_env_text(_filled("minimo")), encoding="utf-8")

    code = config_validate.main(
        ["--env-file", str(env), "--profile", "padrao", "--domains-path", str(PACK)]
    )

    assert code == EXIT_INVALID  # padrao requires an LLM key
    assert "OPENAI_API_KEY" in capsys.readouterr().out


def test_main_unreadable_file_exits_2(tmp_path, capsys) -> None:
    code = config_validate.main(["--env-file", str(tmp_path / "missing.env")])

    assert code == EXIT_UNREADABLE
    assert capsys.readouterr().out == ""


def test_main_without_file_reads_only_known_names(monkeypatch, capsys) -> None:
    for name, value in _filled("minimo").items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DOMAINS_PATH", str(PACK))
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")

    code = config_validate.main([])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "ambiente do processo" in out and "SOME_UNRELATED_VAR" not in out


# --- wiring into install, smoke and start -----------------------------------------


def test_install_validates_inside_the_image_before_starting() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    validate_at = text.index("python -m scripts.config_validate --env-file - < .env")

    assert "run --rm --no-deps -T app" in text
    assert validate_at < text.index("up -d --wait")
    assert validate_at > text.index("build app")
    assert "--no-build" in text[validate_at:]


def test_install_lists_pending_values_by_name_only() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert "<set-(private|provider)-value>' | cut -d= -f1" in text


def test_install_profile_flag_is_documented_and_refused_with_existing_env() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    header = text.split("set -euo pipefail")[0]

    assert "--profile minimo|padrao|completo" in header
    assert "its CONFIG_PROFILE decides the profile" in text
    assert re.search(r"padrao\|completo\) TEMPLATE=\"deploy/profiles/\$\{PROFILE\}\.env\.example\"", text)


def test_install_report_includes_the_validation() -> None:
    assert "## Configuracao (config validate)" in INSTALL_SH.read_text(encoding="utf-8")


def test_smoke_runs_config_validate_and_checks_for_leaks() -> None:
    text = SMOKE_SH.read_text(encoding="utf-8")

    assert "python -m scripts.config_validate --env-file - < .env" in text
    assert "leaked into the config validate output" in text


@pytest.mark.parametrize("script", ["safe_start.py", "post_install.py"])
def test_start_time_config_errors_point_to_the_validator(script) -> None:
    text = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")

    assert "run python -m scripts.config_validate for every reason" in text
