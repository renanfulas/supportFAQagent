from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import check_runtime_capacity as capacity


def test_disk_check_is_critical_when_free_space_is_too_low(monkeypatch) -> None:
    usage = SimpleNamespace(
        total=100 * 1024**3,
        used=80 * 1024**3,
        free=1 * 1024**3,
    )
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda path: usage)

    check = capacity.disk_check(
        path="/",
        warning=75.0,
        critical=90.0,
        min_free_gb=2.0,
    )

    assert check.status == "critical"
    assert check.blocking is True
    assert "free_gb=1.0" in check.detail


def test_postgres_like_volumes_are_protected() -> None:
    protected = capacity.protected_postgres_volumes(
        [
            "supportfaq_db",
            "app_uploads",
            "n8n_n8n_data",
            "supportfaq_pgvector_data",
        ]
    )

    assert protected == ["supportfaq_db", "supportfaq_pgvector_data"]


def test_docker_checks_block_when_no_postgres_volume_is_detected(monkeypatch) -> None:
    monkeypatch.setattr(capacity, "docker_volume_names", lambda: ["frontend_cache"])
    monkeypatch.setattr(capacity, "docker_postgres_mount_count", lambda: 0)
    monkeypatch.setattr(
        capacity,
        "docker_system_df_check",
        lambda require_docker: capacity.Check("docker_system_df", "ok", "ok", False),
    )

    checks = capacity.docker_checks(require_docker=False)

    assert any(
        check.name == "postgres_volume_guard"
        and check.status == "unknown"
        and check.blocking is True
        for check in checks
    )


def test_docker_checks_accept_postgres_container_mount(monkeypatch) -> None:
    monkeypatch.setattr(capacity, "docker_volume_names", lambda: ["anonymous-id"])
    monkeypatch.setattr(capacity, "docker_postgres_mount_count", lambda: 1)
    monkeypatch.setattr(
        capacity,
        "docker_system_df_check",
        lambda require_docker: capacity.Check("docker_system_df", "ok", "ok", False),
    )

    checks = capacity.docker_checks(require_docker=False)

    assert any(
        check.name == "postgres_volume_guard"
        and check.status == "present"
        and check.blocking is False
        and "protected_container_mount_count=1" in check.detail
        for check in checks
    )


def test_docker_checks_skip_volume_guard_when_daemon_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(capacity, "docker_volume_names", lambda: None)
    monkeypatch.setattr(
        capacity,
        "docker_system_df_check",
        lambda require_docker: capacity.Check(
            "docker_system_df",
            "error",
            "docker system df failed",
            require_docker,
        ),
    )

    checks = capacity.docker_checks(require_docker=False)

    assert any(
        check.name == "postgres_volume_guard"
        and check.status == "skipped"
        and check.blocking is False
        for check in checks
    )


def test_cleanup_policy_forbids_volume_prune_without_failing_the_check() -> None:
    check = capacity.cleanup_policy_check()

    assert check.status == "safe_commands_only"
    assert "docker volume prune" in check.detail
    assert "docker system prune --volumes" in check.detail
    assert check.blocking is False


def test_json_report_is_sanitized_and_structured() -> None:
    report = capacity.render_json(
        [
            capacity.Check(
                "disk_capacity",
                "ok",
                "used_percent=50.0 free_gb=10.0 path=/",
                False,
            )
        ]
    )
    payload = json.loads(report)

    assert payload["mode"] == "read-only"
    assert payload["status"] == "ok"
    assert payload["safety"]["postgres_volumes"] == "protected"
