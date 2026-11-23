"""Safe start for the production container.

Runs before the API accepts traffic and only then hands the process to uvicorn:

1. Loads Settings (fails fast on invalid production config, e.g. no API key).
2. ``STARTUP_MIGRATIONS=auto`` (default): bootstraps a **new, empty** database with
   the same sequence as the CI gate (``.github/workflows/phase0-gates.yml``),
   under an advisory lock so several replicas starting together do not race.
   A database that already went past the bootstrap is never migrated here:
   new migrations on a database with data follow the snapshot runbook
   (docs/runbooks/phase0-snapshot-restore.md). ``off`` skips this step.
3. Readiness gate: waits until ``HealthService.readiness()`` is not
   ``unavailable`` (``degraded`` is allowed) or the timeout expires. On timeout
   the process exits non-zero with a sanitized component summary, so the
   container never serves with pending migrations or missing Postgres.
4. ``exec`` uvicorn, so it becomes PID 1 and receives the container signals.

``--check`` runs steps 1-3 and exits without serving (operator preflight).

Nothing here prints the database URL, secrets or raw identifiers.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from scripts.migrate import MigrationError, advisory_lock, migration_files


BOOTSTRAP_LOCK_KEY = 734_291_007
# Ultima migration antes do contrato de privacidade da conversa (007), que so
# passa depois do backfill marcar o contrato pronto.
BOOTSTRAP_PRE_CONTRACT_TARGET = "006_conversations_messages.sql"
BOOTSTRAP_STEPS: tuple[tuple[str, ...], ...] = (
    ("scripts.migrate", "apply", "--target", BOOTSTRAP_PRE_CONTRACT_TARGET),
    (
        "scripts.backfill_conversation_privacy",
        "--verify-contract-ready",
        "--quiet-period-seconds",
        "0",
    ),
    ("scripts.migrate", "apply"),
    ("scripts.migrate", "verify"),
)
MODES = ("auto", "off")
DEFAULT_MODE = "auto"
DEFAULT_READINESS_TIMEOUT_SECONDS = 60.0
DEFAULT_LOCK_TIMEOUT_SECONDS = 300.0
POLL_INTERVAL_SECONDS = 2.0


class StartupError(RuntimeError):
    """Operator-facing failure; the message is safe to print."""


@dataclass(frozen=True)
class DatabaseState:
    applied: frozenset[str]
    has_domains_table: bool
    has_conversation_rows: bool


Runner = Callable[[Sequence[str]], int]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        mode = _mode()
        readiness_timeout = _positive_float_env(
            "STARTUP_READINESS_TIMEOUT_SECONDS", DEFAULT_READINESS_TIMEOUT_SECONDS
        )
        lock_timeout = _positive_float_env(
            "STARTUP_LOCK_TIMEOUT_SECONDS", DEFAULT_LOCK_TIMEOUT_SECONDS
        )
        argv_uvicorn = uvicorn_argv(os.getenv("PORT", "8000"))
    except StartupError as exc:
        _log(str(exc))
        return 2

    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        _log("configuration is invalid; check the .env against deploy/production.env.example")
        return 2

    try:
        from app.db.runtime import DatabaseRuntime

        runtime = DatabaseRuntime(settings)
        if mode == "auto" and runtime.pool_enabled and settings.database_url:
            bootstrap_database(
                settings.database_url,
                lock_timeout_seconds=lock_timeout,
                connect_timeout_seconds=readiness_timeout,
                hash_secret_present=bool(os.getenv("PERSISTENCE_HASH_SECRET", "").strip()),
            )
        wait_until_ready(runtime, timeout_seconds=readiness_timeout)
    except StartupError as exc:
        _log(str(exc))
        return 1

    if args.check:
        _log("startup check passed")
        return 0
    _log("readiness passed; starting the API")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(argv_uvicorn[0], argv_uvicorn)
    return 0  # pragma: no cover - execvp does not return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the bootstrap and the readiness gate, then exit without serving",
    )
    return parser.parse_args(argv)


def uvicorn_argv(port: str) -> list[str]:
    if not port.isdigit():
        raise StartupError("PORT must be a number")
    return [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--no-server-header",
    ]


# --- bootstrap -------------------------------------------------------------------


def bootstrap_plan(state: DatabaseState, files: Sequence[Path]) -> bool:
    """Return True when the bootstrap must run; raise when it must not touch the DB."""

    names = [path.name for path in files]
    if BOOTSTRAP_PRE_CONTRACT_TARGET not in names:
        raise StartupError(f"bootstrap target missing: {BOOTSTRAP_PRE_CONTRACT_TARGET}")
    pre_contract = set(names[: names.index(BOOTSTRAP_PRE_CONTRACT_TARGET) + 1])

    if not state.applied and state.has_domains_table:
        raise StartupError(
            "database has tables but no migration ledger; baseline it manually "
            "(python -m scripts.migrate baseline) before starting"
        )
    if not state.applied.issubset(pre_contract):
        # Ja passou do bootstrap: migration nova aqui so pelo runbook com snapshot.
        return False
    if state.has_conversation_rows:
        raise StartupError(
            "database already has conversations; apply migrations with the "
            "snapshot runbook (docs/runbooks/phase0-snapshot-restore.md)"
        )
    return True


def bootstrap_database(
    database_url: str,
    *,
    lock_timeout_seconds: float,
    connect_timeout_seconds: float,
    hash_secret_present: bool,
    runner: Runner | None = None,
    connect: Callable[[str], Any] | None = None,
) -> bool:
    """Bootstrap a new database under an advisory lock. Returns True if it ran."""

    connection = _connect_with_retry(
        database_url,
        timeout_seconds=connect_timeout_seconds,
        connect=connect or _psycopg_connect,
    )
    try:
        with advisory_lock(
            connection,
            key=BOOTSTRAP_LOCK_KEY,
            timeout_seconds=lock_timeout_seconds,
        ):
            # Estado lido dentro do lock: a segunda replica ve o banco ja pronto.
            if not bootstrap_plan(read_database_state(connection), migration_files()):
                return False
            if not hash_secret_present:
                raise StartupError(
                    "PERSISTENCE_HASH_SECRET is required before the first migration"
                )
            run_bootstrap_steps(runner or _run_module)
            return True
    except MigrationError as exc:
        raise StartupError(str(exc)) from exc
    finally:
        connection.close()


def run_bootstrap_steps(runner: Runner) -> None:
    _log("new database detected; applying the bootstrap migrations")
    for step in BOOTSTRAP_STEPS:
        if runner(step) != 0:
            raise StartupError(f"bootstrap step failed: {' '.join(step[:2])}")
    _log("bootstrap migrations applied")


def read_database_state(connection: Any) -> DatabaseState:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              current_schema(),
              to_regclass(format('%I.%I', current_schema(), 'schema_migrations')) IS NOT NULL,
              to_regclass(format('%I.%I', current_schema(), 'domains')) IS NOT NULL,
              to_regclass(format('%I.%I', current_schema(), 'conversations')) IS NOT NULL
            """
        )
        schema, has_ledger, has_domains, has_conversations = cursor.fetchone()
        applied: set[str] = set()
        if has_ledger:
            cursor.execute(
                sql.SQL("SELECT name FROM {}").format(
                    sql.Identifier(str(schema), "schema_migrations")
                )
            )
            applied = {str(row[0]) for row in cursor.fetchall()}
        has_rows = False
        if has_conversations:
            cursor.execute(
                sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(
                    sql.Identifier(str(schema), "conversations")
                )
            )
            has_rows = bool(cursor.fetchone()[0])
    return DatabaseState(
        applied=frozenset(applied),
        has_domains_table=bool(has_domains),
        has_conversation_rows=has_rows,
    )


# --- readiness gate --------------------------------------------------------------


def wait_until_ready(
    runtime: Any,
    *,
    timeout_seconds: float,
    readiness: Callable[[Any], dict[str, Any]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    probe = readiness or _readiness
    deadline = clock() + timeout_seconds
    snapshot: dict[str, Any] = {}
    try:
        while True:
            snapshot = probe(runtime)
            if snapshot.get("status") != "unavailable":
                return snapshot
            if clock() >= deadline:
                raise StartupError(
                    "readiness did not pass within "
                    f"{timeout_seconds:g}s: {summarize_unavailable(snapshot)}"
                )
            sleep(POLL_INTERVAL_SECONDS)
    finally:
        # O uvicorn abre o proprio pool; nada deste processo pode sobrar aberto.
        runtime.close()


def summarize_unavailable(snapshot: dict[str, Any]) -> str:
    parts = []
    for name, component in sorted(snapshot.get("components", {}).items()):
        if component.get("status") != "unavailable":
            continue
        detail = component.get("reason")
        if not detail and component.get("pending_count"):
            detail = f"pending={component['pending_count']}"
        parts.append(f"{name}({detail})" if detail else name)
    return ", ".join(parts) or "unknown"


def _readiness(runtime: Any) -> dict[str, Any]:
    from app.core.errors import DatabaseUnavailableError
    from app.health.service import HealthService

    try:
        runtime.open()
    except DatabaseUnavailableError:
        pass  # HealthService reporta o banco como unavailable.
    return HealthService(runtime).readiness()


# --- helpers ---------------------------------------------------------------------


def _connect_with_retry(
    database_url: str,
    *,
    timeout_seconds: float,
    connect: Callable[[str], Any],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    deadline = clock() + timeout_seconds
    while True:
        try:
            return connect(database_url)
        except Exception:
            if clock() >= deadline:
                raise StartupError(
                    f"database unreachable after {timeout_seconds:g}s; no migration was applied"
                ) from None
            sleep(POLL_INTERVAL_SECONDS)


def _psycopg_connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5")),
    )


def _run_module(step: Sequence[str]) -> int:
    module, *arguments = step
    return subprocess.run([sys.executable, "-m", module, *arguments], check=False).returncode


def _mode() -> str:
    mode = os.getenv("STARTUP_MIGRATIONS", DEFAULT_MODE).strip().lower() or DEFAULT_MODE
    if mode not in MODES:
        raise StartupError(f"STARTUP_MIGRATIONS must be one of: {', '.join(MODES)}")
    return mode


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise StartupError(f"{name} must be a positive number") from None
    if value <= 0:
        raise StartupError(f"{name} must be a positive number")
    return value


def _log(message: str) -> None:
    print(f"safe_start: {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
