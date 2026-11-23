"""Unit tests for the container safe start (scripts/safe_start.py).

They run without PostgreSQL: the bootstrap decision, the step sequence and the
readiness gate are exercised with fakes. The real sequence runs in the Docker
smoke described in docs/runbooks/docker-install.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import safe_start
from scripts.migrate import migration_files
from scripts.safe_start import (
    BOOTSTRAP_PRE_CONTRACT_TARGET,
    BOOTSTRAP_STEPS,
    DatabaseState,
    StartupError,
    bootstrap_plan,
    run_bootstrap_steps,
    summarize_unavailable,
    uvicorn_argv,
    wait_until_ready,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FILES = migration_files()
NAMES = [path.name for path in FILES]
PRE_CONTRACT = NAMES[: NAMES.index(BOOTSTRAP_PRE_CONTRACT_TARGET) + 1]


@pytest.fixture(autouse=True)
def _fresh_settings():
    # get_settings() e lru_cache: cada teste de main() monta o proprio ambiente.
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _state(applied=(), *, domains=False, rows=False) -> DatabaseState:
    return DatabaseState(
        applied=frozenset(applied),
        has_domains_table=domains,
        has_conversation_rows=rows,
    )


# --- bootstrap decision ------------------------------------------------------------


def test_empty_database_is_bootstrapped() -> None:
    assert bootstrap_plan(_state(), FILES) is True


def test_interrupted_bootstrap_resumes_before_the_contract_migration() -> None:
    # 001..006 aplicadas e o processo caiu antes do backfill: a sequencia e idempotente.
    assert bootstrap_plan(_state(PRE_CONTRACT, domains=True), FILES) is True


def test_initialized_database_is_never_migrated_at_start() -> None:
    assert bootstrap_plan(_state(NAMES, domains=True, rows=True), FILES) is False
    # Mesmo com migration nova pendente: so pelo runbook com snapshot.
    assert bootstrap_plan(_state(NAMES[:-1], domains=True, rows=True), FILES) is False


def test_tables_without_ledger_require_manual_baseline() -> None:
    with pytest.raises(StartupError, match="baseline"):
        bootstrap_plan(_state(domains=True), FILES)


def test_pre_contract_database_with_conversations_requires_snapshot_runbook() -> None:
    with pytest.raises(StartupError, match="snapshot"):
        bootstrap_plan(_state(PRE_CONTRACT, domains=True, rows=True), FILES)


def test_bootstrap_target_must_exist_in_migrations() -> None:
    files = [path for path in FILES if path.name != BOOTSTRAP_PRE_CONTRACT_TARGET]

    with pytest.raises(StartupError, match="target missing"):
        bootstrap_plan(_state(), files)


def test_bootstrap_steps_match_the_ci_gate_sequence() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "phase0-gates.yml").read_text(
        encoding="utf-8"
    )
    lines = [line.strip() for line in workflow.splitlines()]
    commands = [f"python -m {' '.join(step)}" for step in BOOTSTRAP_STEPS]

    # Mesma ordem do gate de CI (linhas inteiras, em subsequencia).
    position = -1
    for command in commands:
        assert command in lines[position + 1 :], (
            f"safe_start drifted from the CI migration sequence: {command}"
        )
        position = lines.index(command, position + 1)


def test_bootstrap_steps_run_in_order_and_stop_on_failure() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(step):
        calls.append(tuple(step))
        return 1 if step[0] == "scripts.backfill_conversation_privacy" else 0

    with pytest.raises(StartupError, match="bootstrap step failed: scripts.backfill"):
        run_bootstrap_steps(runner)

    assert calls == list(BOOTSTRAP_STEPS[:2])


# --- bootstrap under the lock -----------------------------------------------------


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        self.connection.queries.append(str(query))

    def fetchone(self):
        return (self.connection.lock_free,)


class _FakeConnection:
    def __init__(self, *, lock_free=True):
        self.lock_free = lock_free
        self.queries: list[str] = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def close(self):
        self.closed = True


def test_bootstrap_reads_state_inside_the_lock_and_closes_connection(monkeypatch) -> None:
    connection = _FakeConnection()
    seen = []

    def fake_state(conn):
        # O lock ja foi pedido antes de ler o estado.
        assert any("pg_try_advisory_lock" in query for query in conn.queries)
        return _state()

    monkeypatch.setattr(safe_start, "read_database_state", fake_state)

    ran = safe_start.bootstrap_database(
        "postgresql://unused",
        lock_timeout_seconds=1,
        connect_timeout_seconds=1,
        hash_secret_present=True,
        runner=lambda step: seen.append(tuple(step)) or 0,
        connect=lambda _url: connection,
    )

    assert ran is True
    assert seen == list(BOOTSTRAP_STEPS)
    assert any("pg_advisory_unlock" in query for query in connection.queries)
    assert connection.closed


def test_bootstrap_refuses_without_hash_secret(monkeypatch) -> None:
    monkeypatch.setattr(safe_start, "read_database_state", lambda _conn: _state())
    connection = _FakeConnection()

    with pytest.raises(StartupError, match="PERSISTENCE_HASH_SECRET"):
        safe_start.bootstrap_database(
            "postgresql://unused",
            lock_timeout_seconds=1,
            connect_timeout_seconds=1,
            hash_secret_present=False,
            runner=lambda _step: pytest.fail("no step may run without the hash secret"),
            connect=lambda _url: connection,
        )
    assert connection.closed


def test_bootstrap_skips_an_initialized_database(monkeypatch) -> None:
    monkeypatch.setattr(
        safe_start, "read_database_state", lambda _conn: _state(NAMES, domains=True)
    )

    ran = safe_start.bootstrap_database(
        "postgresql://unused",
        lock_timeout_seconds=1,
        connect_timeout_seconds=1,
        hash_secret_present=True,
        runner=lambda _step: pytest.fail("initialized database must not be migrated"),
        connect=lambda _url: _FakeConnection(),
    )

    assert ran is False


def test_lock_timeout_becomes_a_startup_error() -> None:
    with pytest.raises(StartupError, match="lock timed out"):
        safe_start.bootstrap_database(
            "postgresql://unused",
            lock_timeout_seconds=0.01,
            connect_timeout_seconds=1,
            hash_secret_present=True,
            runner=lambda _step: 0,
            connect=lambda _url: _FakeConnection(lock_free=False),
        )


def test_unreachable_database_error_does_not_echo_the_url() -> None:
    clock = iter([0.0, 5.0])

    def refuse(_url):
        raise OSError("connection refused to postgresql://user:s3cret@db/x")

    with pytest.raises(StartupError) as excinfo:
        safe_start._connect_with_retry(
            "postgresql://user:s3cret@db/x",
            timeout_seconds=1,
            connect=refuse,
            clock=lambda: next(clock),
            sleep=lambda _s: None,
        )

    assert "s3cret" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


# --- readiness gate -----------------------------------------------------------------


class _Runtime:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def _snapshot(status, **components):
    return {"status": status, "components": components}


def test_gate_waits_until_readiness_passes_and_closes_the_pool() -> None:
    runtime = _Runtime()
    answers = iter(
        [
            _snapshot("unavailable", database={"status": "unavailable"}),
            _snapshot("degraded", outbox={"status": "degraded"}),
        ]
    )
    sleeps = []

    snapshot = wait_until_ready(
        runtime,
        timeout_seconds=10,
        readiness=lambda _rt: next(answers),
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )

    assert snapshot["status"] == "degraded"
    assert len(sleeps) == 1
    assert runtime.closed == 1


def test_gate_times_out_with_a_sanitized_summary() -> None:
    runtime = _Runtime()
    clock = iter([0.0, 0.0, 61.0])
    snapshot = _snapshot(
        "unavailable",
        database={"status": "ok"},
        migrations={"status": "unavailable", "pending_count": 2},
        retrieval={"status": "unavailable", "reason": "domain_missing_or_inactive"},
    )

    with pytest.raises(StartupError) as excinfo:
        wait_until_ready(
            runtime,
            timeout_seconds=60,
            readiness=lambda _rt: snapshot,
            clock=lambda: next(clock),
            sleep=lambda _s: None,
        )

    assert str(excinfo.value) == (
        "readiness did not pass within 60s: "
        "migrations(pending=2), retrieval(domain_missing_or_inactive)"
    )
    assert runtime.closed == 1


def test_summary_names_postgres_required() -> None:
    snapshot = _snapshot(
        "unavailable", database={"status": "unavailable", "reason": "postgres_required"}
    )

    assert summarize_unavailable(snapshot) == "database(postgres_required)"


# --- main -------------------------------------------------------------------------


def _production_env(monkeypatch, **overrides) -> None:
    values = {
        "APP_ENV": "production",
        "API_SECRET_KEY": "x" * 32,
        "PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://unused",
        "PERSISTENCE_HASH_SECRET": "y" * 32,
        "STARTUP_MIGRATIONS": "auto",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def _patch_pipeline(monkeypatch, *, ready="ok"):
    calls = {"bootstrap": 0, "exec": None}

    def fake_bootstrap(*_args, **_kwargs):
        calls["bootstrap"] += 1
        return True

    monkeypatch.setattr(safe_start, "bootstrap_database", fake_bootstrap)
    monkeypatch.setattr(
        safe_start,
        "_readiness",
        lambda _rt: _snapshot(ready, database={"status": ready, "reason": "x"}),
    )
    monkeypatch.setattr(safe_start.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        safe_start.os, "execvp", lambda file, argv: calls.__setitem__("exec", (file, argv))
    )
    return calls


def test_main_bootstraps_gates_and_execs_uvicorn(monkeypatch) -> None:
    _production_env(monkeypatch, PORT="8000")
    calls = _patch_pipeline(monkeypatch)

    assert safe_start.main([]) == 0
    assert calls["bootstrap"] == 1
    assert calls["exec"] == ("uvicorn", uvicorn_argv("8000"))


def test_main_check_mode_never_serves(monkeypatch) -> None:
    _production_env(monkeypatch)
    calls = _patch_pipeline(monkeypatch)

    assert safe_start.main(["--check"]) == 0
    assert calls["exec"] is None


def test_main_off_mode_skips_bootstrap_but_keeps_the_gate(monkeypatch) -> None:
    _production_env(monkeypatch, STARTUP_MIGRATIONS="off", STARTUP_READINESS_TIMEOUT_SECONDS="0.01")
    calls = _patch_pipeline(monkeypatch, ready="unavailable")

    assert safe_start.main([]) == 1
    assert calls["bootstrap"] == 0
    assert calls["exec"] is None


def test_main_refuses_unknown_mode(monkeypatch) -> None:
    _production_env(monkeypatch, STARTUP_MIGRATIONS="apply-everything")
    calls = _patch_pipeline(monkeypatch)

    assert safe_start.main([]) == 2
    assert calls["exec"] is None


def test_main_refuses_invalid_production_config(monkeypatch, capsys) -> None:
    _production_env(monkeypatch, API_SECRET_KEY=None)
    monkeypatch.chdir(REPO_ROOT / "tests")  # nenhum .env local entra no Settings
    calls = _patch_pipeline(monkeypatch)

    assert safe_start.main([]) == 2
    assert calls["exec"] is None
    assert "configuration is invalid" in capsys.readouterr().err


def test_main_without_postgres_in_production_does_not_start(monkeypatch, capsys) -> None:
    _production_env(
        monkeypatch,
        PERSISTENCE_BACKEND="disabled",
        STARTUP_READINESS_TIMEOUT_SECONDS="0.01",
    )
    calls = _patch_pipeline(monkeypatch)

    def real_readiness(runtime):
        from app.health.service import HealthService

        return HealthService(runtime).readiness()

    monkeypatch.setattr(safe_start, "_readiness", real_readiness)

    assert safe_start.main([]) == 1
    assert calls["bootstrap"] == 0  # sem pool, nada a migrar
    assert calls["exec"] is None
    assert "database(postgres_required)" in capsys.readouterr().err


def test_port_must_be_numeric() -> None:
    with pytest.raises(StartupError):
        uvicorn_argv("8000; rm -rf /")
