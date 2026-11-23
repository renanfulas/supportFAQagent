"""Guards for the production Docker package (Dockerfile + compose + env example).

These run without Docker: they read the packaging files and fail if a security
rule regresses (secret in the build context, root user, public port, literal
secret, client pack mounted writable). Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
COMPOSE_FILE = REPO_ROOT / "docker-compose.prod.yml"
ENV_EXAMPLE = REPO_ROOT / "deploy" / "production.env.example"

ALLOWED_BUILD_CONTEXT = {"pyproject.toml", "app/", "scripts/", "migrations/", "domains/"}
SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.IGNORECASE)
PLACEHOLDER = "<set-private-value>"
# Variables read by docker compose itself, not by the app's Settings.
COMPOSE_ONLY_VARS = {
    "COMPOSE_PROFILES",
    "CLIENT_PACK_DIR",
    "APP_PORT",
    "FORWARDED_ALLOW_IPS",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
}


def _dockerignore_patterns() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _dockerfile_instructions() -> list[tuple[str, str]]:
    """Return (INSTRUCTION, args) pairs, joining backslash continuations."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Drop heredoc bodies so their lines are not parsed as instructions.
    text = re.sub(r"<<'PY'\n.*?\nPY\n", "\n", text, flags=re.S)
    text = re.sub(r"\\\n", " ", text)
    instructions = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keyword, _, args = stripped.partition(" ")
        instructions.append((keyword.upper(), args.strip()))
    return instructions


def _final_stage(instructions: list[tuple[str, str]]) -> list[tuple[str, str]]:
    last_from = max(i for i, (keyword, _) in enumerate(instructions) if keyword == "FROM")
    return instructions[last_from:]


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _env_example() -> dict[str, str]:
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        assert separator, f"malformed line in env example: {key!r}"
        values[key.strip()] = value.strip()
    return values


# --- build context -------------------------------------------------------------


def test_dockerignore_is_a_deny_all_allowlist() -> None:
    patterns = _dockerignore_patterns()

    assert patterns[0] == "*", "the build context must start from deny-all"
    allowed = {pattern[1:] for pattern in patterns if pattern.startswith("!")}
    assert allowed == ALLOWED_BUILD_CONTEXT


@pytest.mark.parametrize("pattern", ["**/.env", "**/.env.*", "**/*.pem", "**/*.key"])
def test_dockerignore_reexcludes_secrets_after_the_allowlist(pattern: str) -> None:
    patterns = _dockerignore_patterns()
    last_allow = max(i for i, item in enumerate(patterns) if item.startswith("!"))

    assert pattern in patterns
    # Later patterns win in .dockerignore, so the exclusion must come after.
    assert patterns.index(pattern) > last_allow


def test_dockerfile_copies_only_allowlisted_paths() -> None:
    for keyword, args in _dockerfile_instructions():
        if keyword != "COPY" or "--from=" in args:
            continue
        parts = [part for part in args.split() if not part.startswith("--")]
        sources, _destination = parts[:-1], parts[-1]
        for source in sources:
            normalized = source if source.endswith(".toml") else source.rstrip("/") + "/"
            assert normalized in ALLOWED_BUILD_CONTEXT, f"COPY of non-allowlisted path: {source}"


# --- image ---------------------------------------------------------------------


def test_final_image_runs_as_non_root_user() -> None:
    users = [args for keyword, args in _final_stage(_dockerfile_instructions()) if keyword == "USER"]

    assert users, "the runtime stage must set USER"
    assert users[-1] not in {"root", "0", "0:0"}


def test_final_image_has_healthcheck_on_liveness_endpoint() -> None:
    healthchecks = [
        args for keyword, args in _final_stage(_dockerfile_instructions()) if keyword == "HEALTHCHECK"
    ]

    assert len(healthchecks) == 1
    assert "/health" in healthchecks[0]
    assert "/health/ready" not in healthchecks[0]


def test_base_images_are_pinned_and_not_latest() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    default_image = re.search(r"^ARG PYTHON_IMAGE=(\S+)$", text, re.M)

    assert default_image is not None
    assert re.fullmatch(r"python:3\.11[\w.-]*", default_image.group(1))
    assert ":latest" not in text


def test_dockerfile_never_declares_secret_values() -> None:
    for keyword, args in _dockerfile_instructions():
        if keyword not in {"ENV", "ARG"}:
            continue
        names = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", args) or [args.split("=")[0]]
        for name in names:
            assert not SECRET_NAME.search(name), f"{keyword} {name} would bake a secret into the image"


def test_image_defaults_to_a_non_development_env() -> None:
    env_args = " ".join(
        args for keyword, args in _final_stage(_dockerfile_instructions()) if keyword == "ENV"
    )
    app_env = re.search(r"APP_ENV=(\S+)", env_args)

    # Outside development, API_SECRET_KEY becomes mandatory: the image fails closed.
    assert app_env is not None
    assert app_env.group(1) not in {"development", "dev", "local"}


def _run_requirements_snippet(extras: str) -> subprocess.CompletedProcess[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    snippet = re.search(r"<<'PY' > /tmp/requirements.txt\n(.*?)\nPY\n", text, re.S)
    assert snippet is not None, "requirements snippet not found in Dockerfile"
    return subprocess.run(
        [sys.executable, "-I", "-c", snippet.group(1)],
        cwd=REPO_ROOT,
        env={**os.environ, "EXTRAS": extras},
        capture_output=True,
        text=True,
        check=False,
    )


def test_image_dependencies_come_from_pyproject() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    result = _run_requirements_snippet("redis")

    assert result.returncode == 0, result.stderr
    expected = project["dependencies"] + project["optional-dependencies"]["redis"]
    assert result.stdout.splitlines() == expected


def test_unknown_extra_fails_the_build() -> None:
    result = _run_requirements_snippet("nao-existe")

    assert result.returncode != 0


# --- compose -------------------------------------------------------------------


def test_app_publishes_only_on_loopback() -> None:
    ports = _compose()["services"]["app"]["ports"]

    assert ports
    assert all(str(port).startswith("127.0.0.1:") for port in ports)


@pytest.mark.parametrize("service", ["postgres", "redis"])
def test_backing_services_publish_no_host_port(service: str) -> None:
    assert "ports" not in _compose()["services"][service]


def test_compose_has_no_literal_secret_values() -> None:
    for name, service in _compose()["services"].items():
        environment = service.get("environment") or {}
        for key, value in environment.items():
            if SECRET_NAME.search(key):
                assert re.fullmatch(r"\$\{[A-Z0-9_]+(:-)?\}", str(value)), (
                    f"{name}.{key} must come from the .env, not a literal"
                )


def test_client_pack_is_mounted_read_only_at_domains_path() -> None:
    app = _compose()["services"]["app"]
    target = app["environment"]["DOMAINS_PATH"]
    mounts = [volume for volume in app["volumes"] if f":{target}" in volume]

    assert len(mounts) == 1
    assert mounts[0].endswith(f":{target}:ro")


def test_app_container_is_hardened() -> None:
    app = _compose()["services"]["app"]

    assert app["read_only"] is True
    assert app["cap_drop"] == ["ALL"]
    assert app["env_file"] == [".env"]


@pytest.mark.parametrize("service", ["app", "postgres", "redis"])
def test_every_service_restarts_drops_privileges_and_rotates_logs(service: str) -> None:
    config = _compose()["services"][service]

    assert config["restart"] == "unless-stopped"
    assert "no-new-privileges:true" in config["security_opt"]
    assert config["logging"]["options"]["max-size"]


def test_optional_services_are_behind_profiles_and_dependencies_are_optional() -> None:
    services = _compose()["services"]

    assert services["postgres"]["profiles"] == ["db"]
    assert services["redis"]["profiles"] == ["redis"]
    for dependency in ("postgres", "redis"):
        assert services["app"]["depends_on"][dependency]["required"] is False


def test_compose_default_extras_exist_in_pyproject() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    build_extras = _compose()["services"]["app"]["build"]["args"]["EXTRAS"]
    default = re.fullmatch(r"\$\{SUPPORTFAQ_EXTRAS:-([\w,-]*)\}", build_extras)

    assert default is not None
    for extra in filter(None, default.group(1).split(",")):
        assert extra in project["optional-dependencies"]


# --- env example ---------------------------------------------------------------


def test_env_example_has_no_real_secret_values() -> None:
    for key, value in _env_example().items():
        if SECRET_NAME.search(key):
            assert value == "" or PLACEHOLDER in value, f"{key} must be empty or a placeholder"


def test_env_example_only_uses_known_variables() -> None:
    known = {field.alias for field in Settings.model_fields.values() if field.alias}
    unknown = set(_env_example()) - known - COMPOSE_ONLY_VARS

    assert unknown == set(), f"typo or unknown variable in env example: {sorted(unknown)}"


def test_env_example_boots_in_production_once_placeholders_are_filled() -> None:
    values = {
        key: value.replace(PLACEHOLDER, "x" * 32)
        for key, value in _env_example().items()
        if key not in COMPOSE_ONLY_VARS
    }

    settings = Settings(_env_file=None, **values)

    assert settings.app_env == "production"
    assert settings.api_secret_key


def test_real_env_files_stay_out_of_git() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".env.*" in ignored
