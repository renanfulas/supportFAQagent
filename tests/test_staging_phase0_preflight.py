from scripts.staging_phase0_preflight import (
    Check,
    collect_checks,
    load_env_file,
    migration_status_check,
    render_report,
)


def test_migration_status_reports_only_counts(monkeypatch) -> None:
    class Result:
        ok = True
        value = "applied: 001_initial_schema.sql\npending: 002_web_auth.sql"

    monkeypatch.setattr(
        "scripts.staging_phase0_preflight.run_sanitized",
        lambda command, env=None: Result(),
    )

    check = migration_status_check()

    assert check.status == "ok"
    assert check.detail == "applied=1 pending=1"
    assert "001_initial_schema.sql" not in check.detail


def test_private_env_file_is_loaded_without_reporting_values(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL='postgresql://private-value'\n# ignored\nEMPTY=\n",
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values["DATABASE_URL"] == "postgresql://private-value"
    assert values["EMPTY"] == ""


def test_exported_environment_wins_over_env_file(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "from-runtime")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "scripts.staging_phase0_preflight.disk_check",
        lambda **kwargs: Check("disk", "ok", "ok", False),
    )
    monkeypatch.setattr(
        "scripts.staging_phase0_preflight.command_check",
        lambda name: Check(name, "present", "ok", False),
    )
    monkeypatch.setattr("scripts.staging_phase0_preflight.environment_checks", lambda env: [])
    monkeypatch.setattr("scripts.staging_phase0_preflight.git_checks", lambda: [])
    monkeypatch.setattr(
        "scripts.staging_phase0_preflight.docker_network_check",
        lambda: Check("network", "present", "ok", False),
    )

    def capture_migration_env(runtime_env):
        captured.update(runtime_env)
        return Check("migration", "ok", "ok", False)

    monkeypatch.setattr(
        "scripts.staging_phase0_preflight.migration_status_check",
        capture_migration_env,
    )

    collect_checks(
        snapshot_confirmed=True,
        path=".",
        warning=75,
        critical=85,
        env_file=str(env_file),
    )

    assert captured["DATABASE_URL"] == "from-runtime"


def test_report_blocks_migration_review_without_snapshot() -> None:
    report = render_report(
        [
            Check(
                name="provider_snapshot",
                status="missing",
                detail="confirmation required",
                blocking=True,
            )
        ]
    )

    assert "ready_for_migration_review: false" in report
    assert "mode: read-only" in report


def test_report_never_claims_it_applies_migrations() -> None:
    report = render_report(
        [Check(name="provider_snapshot", status="confirmed", detail="ok", blocking=False)]
    )

    assert "ready_for_migration_review: true" in report
    assert "never runs baseline, apply, restore" in report
