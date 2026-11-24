"""Post-install steps of a company installation, run inside the app container.

    docker compose -f docker-compose.prod.yml run --rm app python -m scripts.post_install \
        [--admin-phone +5511999999999 --admin-name "Nome"] [--skip-evals]

Called by ``deploy/install.sh`` after the stack is up (the safe start already
migrated the database and passed readiness). Steps:

1. Readiness snapshot (same contract as ``/health/ready``).
2. Registers every domain of the client pack in the ``domains`` table, without
   needing an embedding key, so conversations are persisted from the first turn.
3. Optionally registers the first support-console operator (needs
   ``IDENTITY_HASH_SECRET``).
4. Runs each domain's confinement evals (``evals/cases.yaml`` and
   ``evals/confinement/*``) that exist.
5. Prints a Markdown installation report on stdout. Everything else goes to
   stderr, so ``> install-report.md`` captures only the report.

The report never contains secrets, the database URL, full phone numbers or raw
session ids. Exit codes: 0 ok, 1 a required step failed, 2 invalid
configuration or arguments, 3 installed but an eval failed.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
import sys
from typing import Any, Callable

from app.domain_engine.scaffold import EVAL_FILES


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_EVALS_FAILED = 3


@dataclass
class Step:
    name: str
    status: str  # ok | skipped | failed
    detail: str


@dataclass
class EvalSummary:
    domain: str
    suite: str
    total: int
    passed: int

    @property
    def failed(self) -> int:
        return self.total - self.passed


@dataclass
class InstallReport:
    app_name: str
    app_env: str
    generated_at: str
    steps: list[Step] = field(default_factory=list)
    domains: list[tuple[str, str]] = field(default_factory=list)
    evals: list[EvalSummary] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str) -> Step:
        step = Step(name, status, detail)
        self.steps.append(step)
        return step

    @property
    def exit_code(self) -> int:
        if any(step.status == "failed" for step in self.steps):
            return EXIT_FAILED
        if any(summary.failed for summary in self.evals):
            return EXIT_EVALS_FAILED
        return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(args.admin_phone) != bool(args.admin_name):
        print("--admin-phone and --admin-name go together", file=sys.stderr)
        return EXIT_CONFIG

    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        print(
            "configuration is invalid; check the .env against deploy/production.env.example",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # Tudo que os passos imprimirem vai para stderr; stdout e so o relatorio.
    with redirect_stdout(sys.stderr):
        report = run_post_install(
            settings,
            admin_phone=args.admin_phone,
            admin_name=args.admin_name,
            skip_evals=args.skip_evals,
        )
    sys.stdout.write(render_markdown(report))
    sys.stdout.flush()
    return report.exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-install steps of a company installation.")
    parser.add_argument("--admin-phone", help="E.164 phone of the first console operator")
    parser.add_argument("--admin-name", help="display name of the first console operator")
    parser.add_argument("--skip-evals", action="store_true", help="do not run domain evals")
    return parser.parse_args(argv)


def run_post_install(
    settings: Any,
    *,
    admin_phone: str | None = None,
    admin_name: str | None = None,
    skip_evals: bool = False,
    connect: Callable[[str], Any] | None = None,
    readiness: Callable[[Any], dict[str, Any]] | None = None,
    run_eval: Callable[[Any, Any], Any] | None = None,
) -> InstallReport:
    from app.domain_engine.loader import DomainLoader

    report = InstallReport(
        app_name=str(settings.app_name),
        app_env=str(settings.app_env),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    snapshot = (readiness or _readiness)(settings)
    ready = snapshot.get("status") != "unavailable"
    report.add(
        "readiness",
        "ok" if ready else "failed",
        f"{snapshot.get('status')}: {_component_summary(snapshot)}",
    )

    loader = DomainLoader(settings.domains_path)
    domains = [loader.load(name) for name in loader.list_domains()]
    domains = [domain for domain in domains if domain is not None]
    report.domains = [(domain.name, domain.display_name) for domain in domains]
    if not domains:
        report.add("domains", "failed", f"no valid domain found in {settings.domains_path}")

    database_url = getattr(settings, "database_url", None)
    if not database_url:
        report.add("register_domains", "skipped", "DATABASE_URL is not set")
    elif not ready:
        report.add("register_domains", "skipped", "readiness did not pass")
    elif domains:
        _register_domains(report, database_url, domains, connect or _connect)

    if admin_phone:
        _register_admin(report, settings, database_url, ready, admin_phone, admin_name or "", connect or _connect)
    else:
        report.add("admin", "skipped", "no --admin-phone given")

    if skip_evals:
        report.add("evals", "skipped", "--skip-evals")
    else:
        _run_evals(report, domains, run_eval or _run_eval_suite)

    report.next_steps = _next_steps(settings, report, admin_registered=bool(admin_phone))
    return report


# --- steps ---------------------------------------------------------------------------


def _register_domains(report: InstallReport, database_url: str, domains: list[Any], connect) -> None:
    from app.db.domain_registry import upsert_domain

    try:
        connection = connect(database_url)
        try:
            with connection.cursor() as cursor:
                for domain in domains:
                    upsert_domain(cursor, name=domain.name, display_name=domain.display_name)
            connection.commit()
        finally:
            connection.close()
    except Exception:
        report.add("register_domains", "failed", "could not write the domains table")
        return
    report.add("register_domains", "ok", f"{len(domains)} domain(s) registered")


def _register_admin(
    report: InstallReport,
    settings: Any,
    database_url: str | None,
    ready: bool,
    phone: str,
    name: str,
    connect,
) -> None:
    secret = getattr(settings, "identity_hash_secret", None)
    if not secret:
        report.add("admin", "failed", "IDENTITY_HASH_SECRET is required to register an operator")
        return
    if not database_url or not ready:
        report.add("admin", "failed", "database is not ready")
        return

    from scripts.manage_staff import upsert_operator

    try:
        connection = connect(database_url)
        try:
            display_name, last4 = upsert_operator(connection, secret, phone, name)
        finally:
            connection.close()
    except ValueError as error:
        report.add("admin", "failed", str(error))
        return
    except Exception:
        report.add("admin", "failed", "could not write the staff_members table")
        return
    report.add("admin", "ok", f"{display_name} (****{last4})")


def _run_evals(report: InstallReport, domains: list[Any], run_eval) -> None:
    from app.evals.loader import EvalSuiteLoader

    loader = EvalSuiteLoader()
    for domain in domains:
        for relative in EVAL_FILES:
            path = domain.root_path / relative
            if not path.exists():
                continue
            suite = loader.load(path)
            if suite is None or suite.domain != domain.name:
                report.add("evals", "failed", f"{domain.name}: invalid suite {relative}")
                continue
            result = run_eval(domain, suite)
            report.evals.append(
                EvalSummary(
                    domain=domain.name,
                    suite=relative,
                    total=int(result.total),
                    passed=int(result.passed),
                )
            )
    if not report.evals and not any(step.name == "evals" for step in report.steps):
        report.add("evals", "skipped", "no eval suite found in the client pack")
        return
    failed = sum(summary.failed for summary in report.evals)
    total = sum(summary.total for summary in report.evals)
    report.add(
        "evals",
        "ok" if not failed else "attention",
        f"{total - failed}/{total} case(s) passed",
    )


def _next_steps(settings: Any, report: InstallReport, *, admin_registered: bool) -> list[str]:
    steps: list[str] = []
    if not (getattr(settings, "openai_api_key", None) or getattr(settings, "anthropic_api_key", None)):
        steps.append(
            "Configurar OPENAI_API_KEY ou ANTHROPIC_API_KEY: sem chave o chat responde "
            "o fallback seguro provider_error."
        )
    if getattr(settings, "retrieval_backend", "lexical") != "pgvector":
        steps.append(
            "Busca lexical ligada. Para busca vetorial: ingerir os dominios com "
            "scripts.ingest_domain_pgvector e trocar RETRIEVAL_BACKEND=pgvector."
        )
    if not getattr(settings, "enable_public_chat_ui", False):
        steps.append(
            "Chat web publico desligado (ENABLE_PUBLIC_CHAT_UI). Ligar so com o reverse proxy HTTPS."
        )
    if admin_registered and not getattr(settings, "enable_support_console", False):
        steps.append(
            "Operador cadastrado, mas o console do time esta desligado (ENABLE_SUPPORT_CONSOLE)."
        )
    if any(summary.failed for summary in report.evals):
        steps.append("Revisar os evals com falha antes de abrir para clientes reais.")
    return steps


# --- defaults (real runtime) ---------------------------------------------------------


def _readiness(settings: Any) -> dict[str, Any]:
    from app.core.errors import DatabaseUnavailableError
    from app.db.runtime import DatabaseRuntime
    from app.health.service import HealthService

    runtime = DatabaseRuntime(settings)
    try:
        try:
            runtime.open()
        except DatabaseUnavailableError:
            pass
        return HealthService(runtime).readiness()
    finally:
        runtime.close()


def _connect(database_url: str) -> Any:
    import os

    import psycopg

    return psycopg.connect(
        database_url,
        connect_timeout=int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5")),
    )


def _run_eval_suite(domain: Any, suite: Any) -> Any:
    from app.evals.runner import DomainEvalRunner

    return DomainEvalRunner().run(domain=domain, suite=suite)


# --- report ------------------------------------------------------------------------


def _component_summary(snapshot: dict[str, Any]) -> str:
    parts = []
    for name, component in sorted(snapshot.get("components", {}).items()):
        status = component.get("status", "?")
        reason = component.get("reason")
        parts.append(f"{name}={status}" + (f"({reason})" if reason else ""))
    return ", ".join(parts) or "no components"


_STATUS_MARK = {"ok": "✅", "skipped": "➖", "attention": "⚠️", "failed": "❌"}


def render_markdown(report: InstallReport) -> str:
    verdict = {
        EXIT_OK: "✅ instalacao concluida",
        EXIT_EVALS_FAILED: "⚠️ instalada, com evals falhando",
        EXIT_FAILED: "❌ instalacao incompleta",
    }[report.exit_code]
    lines = [
        f"# Relatorio de instalacao - {report.app_name}",
        "",
        f"- Gerado em: {report.generated_at}",
        f"- Ambiente: `{report.app_env}`",
        f"- Resultado: {verdict}",
        "",
        "## Passos",
        "",
        "| Passo | Status | Detalhe |",
        "| --- | --- | --- |",
    ]
    for step in report.steps:
        mark = _STATUS_MARK.get(step.status, step.status)
        lines.append(f"| {step.name} | {mark} {step.status} | {_cell(step.detail)} |")

    lines += ["", "## Dominios", ""]
    if report.domains:
        lines += [f"- `{name}`: {_cell(display)}" for name, display in report.domains]
    else:
        lines.append("- nenhum")

    if report.evals:
        lines += ["", "## Evals de confinamento", "", "| Dominio | Suite | Passaram |", "| --- | --- | --- |"]
        for summary in report.evals:
            mark = "✅" if not summary.failed else "⚠️"
            lines.append(
                f"| `{summary.domain}` | `{summary.suite}` | {mark} {summary.passed}/{summary.total} |"
            )

    if report.next_steps:
        lines += ["", "## Proximos passos", ""]
        lines += [f"- {item}" for item in report.next_steps]
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
