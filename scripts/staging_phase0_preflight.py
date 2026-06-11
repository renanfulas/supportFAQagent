from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys


REQUIRED_ENV = (
    "APP_ENV",
    "API_SECRET_KEY",
    "DATABASE_URL",
    "PERSISTENCE_HASH_SECRET",
    "OUTBOX_WEBHOOK_SECRET",
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    blocking: bool


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a sanitized, read-only Phase 0 staging preflight."
    )
    parser.add_argument(
        "--snapshot-confirmed",
        action="store_true",
        help="Confirm a completed provider snapshot exists before migration.",
    )
    parser.add_argument("--path", default="/", help="Filesystem path to inspect.")
    parser.add_argument("--warning", type=float, default=75.0)
    parser.add_argument("--critical", type=float, default=85.0)
    parser.add_argument("--env-file", default=".env", help="Private runtime env file.")
    parser.add_argument("--output", help="Write a sanitized Markdown report.")
    args = parser.parse_args()

    checks = collect_checks(
        snapshot_confirmed=args.snapshot_confirmed,
        path=args.path,
        warning=args.warning,
        critical=args.critical,
        env_file=args.env_file,
    )
    report = render_report(checks)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0 if all(not check.blocking for check in checks) else 1


def collect_checks(
    *,
    snapshot_confirmed: bool,
    path: str,
    warning: float,
    critical: float,
    env_file: str,
) -> list[Check]:
    runtime_env = {**load_env_file(Path(env_file)), **os.environ}
    checks = [
        Check(
            name="provider_snapshot",
            status="confirmed" if snapshot_confirmed else "missing",
            detail="completed snapshot confirmed" if snapshot_confirmed else "confirmation required",
            blocking=not snapshot_confirmed,
        ),
        disk_check(path=path, warning=warning, critical=critical),
        command_check("git"),
        command_check("docker"),
        command_check("psql"),
    ]
    checks.extend(environment_checks(runtime_env))
    checks.extend(git_checks())
    checks.append(docker_network_check())
    checks.append(migration_status_check(runtime_env))
    return checks


def disk_check(*, path: str, warning: float, critical: float) -> Check:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return Check("disk_capacity", "error", "path unavailable", True)
    percent = round((usage.used / usage.total) * 100, 2)
    if percent >= critical:
        return Check("disk_capacity", "critical", f"used_percent={percent}", True)
    if percent >= warning:
        return Check("disk_capacity", "warning", f"used_percent={percent}", False)
    return Check("disk_capacity", "ok", f"used_percent={percent}", False)


def command_check(name: str) -> Check:
    present = shutil.which(name) is not None
    return Check(
        name=f"command_{name}",
        status="present" if present else "missing",
        detail="available" if present else "not available",
        blocking=name in {"git"} and not present,
    )


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value.startswith(("'", '"')):
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def environment_checks(runtime_env: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    for name in REQUIRED_ENV:
        present = bool(runtime_env.get(name, "").strip())
        checks.append(
            Check(
                name=f"env_{name}",
                status="present" if present else "missing",
                detail="value intentionally hidden",
                blocking=not present,
            )
        )
    return checks


def git_checks() -> list[Check]:
    branch = run_sanitized(["git", "branch", "--show-current"])
    commit = run_sanitized(["git", "rev-parse", "--short", "HEAD"])
    dirty = run_sanitized(["git", "status", "--porcelain", "--untracked-files=no"])
    return [
        Check("git_branch", "ok" if branch.ok else "error", branch.value or "unavailable", not branch.ok),
        Check("git_commit", "ok" if commit.ok else "error", commit.value or "unavailable", not commit.ok),
        Check(
            "git_tracked_worktree",
            "clean" if dirty.ok and not dirty.value else "dirty",
            "tracked files clean" if dirty.ok and not dirty.value else "tracked changes present",
            not dirty.ok or bool(dirty.value),
        ),
    ]


def docker_network_check() -> Check:
    result = run_sanitized(["docker", "network", "inspect", "supportfaq_internal"])
    return Check(
        "docker_network_supportfaq_internal",
        "present" if result.ok else "missing",
        "private network available" if result.ok else "private network unavailable",
        not result.ok,
    )


def migration_status_check(runtime_env: dict[str, str] | None = None) -> Check:
    result = run_sanitized(
        [sys.executable, "-m", "scripts.migrate", "status"],
        env=runtime_env,
    )
    if not result.ok:
        return Check("migration_status", "error", "status command failed", True)
    lines = [line.strip() for line in result.value.splitlines() if line.strip()]
    applied = sum(line.startswith("applied:") for line in lines)
    pending = sum(line.startswith("pending:") for line in lines)
    valid = bool(lines) and applied + pending == len(lines)
    return Check(
        "migration_status",
        "ok" if valid else "error",
        f"applied={applied} pending={pending}" if valid else "unexpected output",
        not valid,
    )


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    value: str


def run_sanitized(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CommandResult(False, "")
    return CommandResult(result.returncode == 0, result.stdout.strip())


def render_report(checks: list[Check]) -> str:
    ready = all(not check.blocking for check in checks)
    lines = [
        "# Phase 0 Staging Preflight",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- ready_for_migration_review: {str(ready).lower()}",
        "- mode: read-only",
        "",
        "## Checks",
        "",
    ]
    for check in checks:
        lines.append(
            f"- {check.name}: status={check.status} blocking={str(check.blocking).lower()} detail={check.detail}"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This command never runs baseline, apply, restore or destructive Docker operations.",
            "- Secret values, DATABASE_URL contents and raw command errors are intentionally hidden.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
