"""Guards for the image CI/publish workflow and the compose smoke script.

They read the files without running Docker or GitHub Actions and fail if the
release path loses a safety rule: publishing outside a version tag, write
permission on PR runs, an untested image being pushed, a floating "latest" tag,
or the smoke script being able to wipe a real installation.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker-image.yml"
SMOKE = REPO_ROOT / "deploy" / "docker-smoke.sh"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict:
    data = _workflow()
    # PyYAML le a chave "on" como booleano True.
    return data.get("on", data.get(True))


def _steps(job: str) -> list[dict]:
    return _workflow()["jobs"][job]["steps"]


def _run_text(job: str) -> str:
    return "\n".join(step.get("run", "") for step in _steps(job))


# --- triggers e permissoes --------------------------------------------------------


def test_runs_on_every_pr_main_and_version_tags_only() -> None:
    triggers = _triggers()

    assert "pull_request" in triggers
    assert "pull_request_target" not in triggers, "PR code must never run with write tokens"
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["tags"] == ["v*.*.*"]


def test_default_token_is_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}
    assert "permissions" not in _workflow()["jobs"]["build-and-smoke"]


def test_only_the_tag_gated_publish_job_can_write_packages() -> None:
    jobs = _workflow()["jobs"]
    writers = [
        name
        for name, job in jobs.items()
        if job.get("permissions", {}).get("packages") == "write"
    ]

    assert writers == ["publish"]
    assert jobs["publish"]["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert jobs["publish"]["needs"] == "build-and-smoke"


def test_only_github_token_secret_is_used() -> None:
    secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", WORKFLOW.read_text(encoding="utf-8")))

    assert secrets == {"GITHUB_TOKEN"}


# --- build, smoke e publicacao ----------------------------------------------------


def test_build_never_pushes_and_feeds_the_smoke() -> None:
    build = next(step for step in _steps("build-and-smoke") if step.get("name") == "Build image")
    smoke = next(step for step in _steps("build-and-smoke") if step.get("name") == "Compose smoke")

    assert build["with"]["push"] is False
    assert build["with"]["load"] is True
    assert smoke["run"] == "bash deploy/docker-smoke.sh"
    assert smoke["env"]["SUPPORTFAQ_IMAGE"] == build["with"]["tags"]


def test_published_image_is_the_tested_one() -> None:
    publish_uses = [step.get("uses", "") for step in _steps("publish")]
    publish_run = _run_text("publish")

    # A publicacao carrega a imagem que passou no smoke; nao builda outra.
    assert not any(uses.startswith("docker/build-push-action") for uses in publish_uses)
    assert "docker build" not in publish_run
    assert "docker load" in publish_run
    assert "docker save" in _run_text("build-and-smoke")


def test_publish_requires_tag_equal_to_pyproject_version() -> None:
    publish_run = _run_text("publish")

    assert 'tomllib.load(open("pyproject.toml","rb"))["project"]["version"]' in publish_run
    assert '[ "$tag" != "v$version" ]' in publish_run
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in publish_run


def test_no_floating_latest_tag_is_published() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert ":latest" not in text
    assert 'for tag in "$VERSION" "$MINOR"' in _run_text("publish")


def test_actions_are_pinned_to_a_version() -> None:
    for job in _workflow()["jobs"]:
        for step in _steps(job):
            uses = step.get("uses")
            if uses:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", uses), uses


# --- script de smoke --------------------------------------------------------------


def test_smoke_is_strict_and_cleans_up() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "trap cleanup EXIT" in text
    assert "down -v --remove-orphans" in text


def test_smoke_cannot_touch_a_real_installation() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    # So apaga volumes de projeto com prefixo de smoke, e nunca pisa num .env real.
    assert 'sfaq-smoke*) ;;' in text
    assert 'if [ -e .env ]; then' in text
    assert text.index('if [ -e .env ]; then') < text.index("trap cleanup EXIT")


def test_smoke_covers_the_safe_start_contract() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    for evidence in (
        "safe_start: new database detected",
        "safe_start: readiness passed",
        "restart re-ran the bootstrap",
        "/health/ready",
        "id -u",
        "leaked into the app log",
    ):
        assert evidence in text, evidence


def test_smoke_secrets_are_random_per_run() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert "secrets.token_hex" in text
    for name in ("API_KEY", "DB_PASSWORD", "HASH_SECRET"):
        assert f"{name}=$(rand)" in text


def test_shell_and_workflow_files_keep_lf_endings() -> None:
    rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "deploy/*.sh text eol=lf" in rules
    assert b"\r\n" not in SMOKE.read_bytes()
