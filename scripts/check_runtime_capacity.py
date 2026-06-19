from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Iterable


PROTECTED_VOLUME_KEYWORDS = (
    "postgres",
    "postgresql",
    "pgdata",
    "pgvector",
    "supportfaq_db",
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    blocking: bool


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a sanitized runtime capacity check without pruning data."
    )
    parser.add_argument("--path", default="/", help="Filesystem path to inspect.")
    parser.add_argument("--warning", type=float, default=75.0)
    parser.add_argument("--critical", type=float, default=85.0)
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=2.0,
        help="Minimum free GiB before the check becomes critical.",
    )
    parser.add_argument(
        "--require-docker",
        action="store_true",
        help="Fail when Docker is unavailable.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument("--output", help="Write the sanitized report to a file.")
    args = parser.parse_args()

    checks = collect_checks(
        path=args.path,
        warning=args.warning,
        critical=args.critical,
        min_free_gb=args.min_free_gb,
        require_docker=args.require_docker,
    )
    if args.format == "json":
        report = render_json(checks)
    else:
        report = render_text(checks)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)
    return exit_code(checks)


def collect_checks(
    *,
    path: str,
    warning: float,
    critical: float,
    min_free_gb: float,
    require_docker: bool,
) -> list[Check]:
    checks = [
        disk_check(path=path, warning=warning, critical=critical, min_free_gb=min_free_gb)
    ]
    docker_present = shutil.which("docker") is not None
    checks.append(
        Check(
            "docker_cli",
            "present" if docker_present else "missing",
            "available" if docker_present else "not available",
            require_docker and not docker_present,
        )
    )
    if docker_present:
        checks.extend(docker_checks(require_docker=require_docker))
    else:
        checks.append(
            Check(
                "docker_cleanup_policy",
                "skipped",
                "docker unavailable; no prune recommendation evaluated",
                False,
            )
        )
    checks.append(cleanup_policy_check())
    return checks


def disk_check(
    *,
    path: str,
    warning: float,
    critical: float,
    min_free_gb: float,
) -> Check:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return Check("disk_capacity", "error", "path unavailable", True)
    used_percent = round((usage.used / usage.total) * 100, 2)
    free_gb = round(usage.free / (1024**3), 2)
    detail = f"used_percent={used_percent} free_gb={free_gb} path={path}"
    if free_gb < min_free_gb:
        return Check("disk_capacity", "critical", detail, True)
    if used_percent >= critical:
        return Check("disk_capacity", "critical", detail, True)
    if used_percent >= warning:
        return Check("disk_capacity", "warning", detail, False)
    return Check("disk_capacity", "ok", detail, False)


def docker_checks(*, require_docker: bool) -> list[Check]:
    checks = [docker_system_df_check(require_docker=require_docker)]
    volumes = docker_volume_names()
    if volumes is None:
        checks.append(
            Check(
                "postgres_volume_guard",
                "skipped",
                "docker volume list unavailable",
                require_docker,
            )
        )
    else:
        protected = protected_postgres_volumes(volumes)
        protected_mount_count = docker_postgres_mount_count()
        checks.append(
            Check(
                "postgres_volume_guard",
                "present" if protected or protected_mount_count else "unknown",
                (
                    "protected_named_volume_count="
                    f"{len(protected)} protected_container_mount_count={protected_mount_count}"
                    if protected or protected_mount_count
                    else "no postgres-like volume name detected"
                ),
                not protected and not protected_mount_count,
            )
        )
    checks.append(
        Check(
            "docker_volume_prune_guard",
            "blocked",
            "never run docker volume prune or docker system prune --volumes on this host",
            False,
        )
    )
    return checks


def docker_system_df_check(*, require_docker: bool) -> Check:
    result = run_sanitized(["docker", "system", "df"])
    if not result.ok:
        return Check(
            "docker_system_df",
            "error",
            "docker system df failed",
            require_docker,
        )
    build_cache_seen = "Build Cache" in result.stdout or "build cache" in result.stdout.lower()
    return Check(
        "docker_system_df",
        "ok" if build_cache_seen else "warning",
        "build cache section present" if build_cache_seen else "build cache section not detected",
        False,
    )


def docker_volume_names() -> list[str] | None:
    result = run_sanitized(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if not result.ok:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def protected_postgres_volumes(volumes: Iterable[str]) -> list[str]:
    protected: list[str] = []
    for volume in volumes:
        normalized = volume.lower()
        if any(keyword in normalized for keyword in PROTECTED_VOLUME_KEYWORDS):
            protected.append(volume)
    return protected


def docker_container_names() -> list[str] | None:
    result = run_sanitized(["docker", "ps", "-a", "--format", "{{.Names}}"])
    if not result.ok:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def docker_postgres_mount_count() -> int:
    containers = docker_container_names()
    if not containers:
        return 0
    count = 0
    for container in containers:
        result = run_sanitized(
            [
                "docker",
                "inspect",
                container,
                "--format",
                "{{.Config.Image}}|{{range .Mounts}}{{.Destination}};{{end}}",
            ]
        )
        normalized = result.stdout.lower()
        if result.ok and "/var/lib/postgresql/data" in normalized:
            if "postgres" in normalized or "pgvector" in normalized:
                count += 1
    return count


def cleanup_policy_check() -> Check:
    return Check(
        "docker_cleanup_policy",
        "safe_commands_only",
        (
            "allowed: docker builder prune --filter until=168h; "
            "forbidden: docker volume prune, docker system prune --volumes"
        ),
        False,
    )


def run_sanitized(command: list[str]) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CommandResult(False, "")
    return CommandResult(result.returncode == 0, result.stdout.strip())


def render_text(checks: list[Check]) -> str:
    lines = [
        "# Runtime Capacity Check",
        "",
        f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"- status: {overall_status(checks)}",
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
            "- This command never removes containers, images, build cache, volumes or PostgreSQL data.",
            "- PostgreSQL-like Docker volumes are treated as protected runtime data.",
            "- Use the output as an alert/preflight signal before a human-approved cleanup.",
        ]
    )
    return "\n".join(lines)


def render_json(checks: list[Check]) -> str:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status(checks),
        "mode": "read-only",
        "checks": [check.__dict__ for check in checks],
        "safety": {
            "destructive_operations": "never",
            "postgres_volumes": "protected",
        },
    }
    return json.dumps(payload, sort_keys=True)


def overall_status(checks: list[Check]) -> str:
    if any(check.blocking and check.status in {"critical", "error", "missing", "unknown"} for check in checks):
        return "critical"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "ok"


def exit_code(checks: list[Check]) -> int:
    status = overall_status(checks)
    if status == "critical":
        return 2
    if status == "warning":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
