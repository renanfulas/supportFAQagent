"""Aggregate a Phase 0 timed-restore drill into sanitized evidence.

This helper is **read-only by construction**: it does not create snapshots,
restore anything, touch the provider, or connect to a database. The operator
runs the read-only checks from `docs/runbooks/phase0-snapshot-restore.md` on the
isolated restored host, then feeds their results and the drill timestamps here.
The helper computes RTO/RPO, enforces the `RTO <= 4h` / `RPO <= 24h` thresholds,
and prints a sanitized evidence block plus the single `restore` verdict that
`scripts.phase0_operational_report` consumes.

Only timestamps and status enums are handled, so the output can never leak
snapshot names, IPs, hostnames, users, credentials or payloads.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.phase0_operational_report import STATUSES

# Read-only checks the operator runs on the restored host (runbook steps 4-8).
SUBCHECKS = (
    "capacity",
    "migrate_verify",
    "readiness",
    "pgvector",
    "outbox",
    "volumes",
    "smoke",
)

DEFAULT_RTO_MAX_HOURS = 4.0
DEFAULT_RPO_MAX_HOURS = 24.0


@dataclass(frozen=True)
class RestoreEvaluation:
    verdict: str  # one of STATUSES
    rto_hours: float | None
    rpo_hours: float | None
    rto_max_hours: float
    rpo_max_hours: float
    rto_ok: bool
    rpo_ok: bool
    subchecks: dict[str, str]
    reason: str


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z`` (UTC)."""
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def duration_hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def evaluate_restore(
    *,
    snapshot_timestamp: datetime | None,
    restore_started_at: datetime | None,
    restore_finished_at: datetime | None,
    latest_data_timestamp: datetime | None,
    subchecks: dict[str, str],
    rto_max_hours: float = DEFAULT_RTO_MAX_HOURS,
    rpo_max_hours: float = DEFAULT_RPO_MAX_HOURS,
) -> RestoreEvaluation:
    unknown = set(subchecks) - set(SUBCHECKS)
    invalid = {s for s in subchecks.values() if s not in STATUSES}
    if unknown or invalid:
        raise ValueError("invalid restore sub-check report")
    resolved = {name: subchecks.get(name, "pending") for name in SUBCHECKS}

    rto_hours: float | None = None
    if restore_started_at and restore_finished_at:
        rto_hours = duration_hours(restore_started_at, restore_finished_at)
    rpo_hours: float | None = None
    if snapshot_timestamp and latest_data_timestamp:
        rpo_hours = abs(duration_hours(latest_data_timestamp, snapshot_timestamp))

    rto_ok = rto_hours is not None and rto_hours <= rto_max_hours
    rpo_ok = rpo_hours is not None and rpo_hours <= rpo_max_hours

    timing_complete = rto_hours is not None and rpo_hours is not None
    negative_timing = (rto_hours is not None and rto_hours < 0) or (
        rpo_hours is not None and rpo_hours < 0
    )

    if not timing_complete or negative_timing:
        verdict = "blocked"
        reason = "timing incompleto ou inconsistente; informe os quatro timestamps"
    elif any(status == "failed" for status in resolved.values()):
        verdict = "failed"
        reason = "um ou mais checks read-only falharam no host restaurado"
    elif not rto_ok or not rpo_ok:
        verdict = "failed"
        reason = "RTO ou RPO acima da meta"
    elif any(status in ("blocked", "pending") for status in resolved.values()):
        verdict = "blocked"
        reason = "um ou mais checks ainda nao foram comprovados"
    else:
        verdict = "passed"
        reason = "restore cronometrado dentro das metas com checks comprovados"

    return RestoreEvaluation(
        verdict=verdict,
        rto_hours=rto_hours,
        rpo_hours=rpo_hours,
        rto_max_hours=rto_max_hours,
        rpo_max_hours=rpo_max_hours,
        rto_ok=rto_ok,
        rpo_ok=rpo_ok,
        subchecks=resolved,
        reason=reason,
    )


def _format_hours(value: float | None) -> str:
    return f"{value:.2f}h" if value is not None else "nao informado"


def render_restore_report(evaluation: RestoreEvaluation) -> str:
    lines = [
        "# Phase 0 Restore Drill Evidence",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        "- host: VPS restaurada isolada (nao o staging oficial)",
        f"- restore verdict: {evaluation.verdict}",
        f"- reason: {evaluation.reason}",
        "",
        "## Metas",
        "",
        f"- rto: {_format_hours(evaluation.rto_hours)} "
        f"(max {evaluation.rto_max_hours:.2f}h) -> {'ok' if evaluation.rto_ok else 'fora da meta'}",
        f"- rpo: {_format_hours(evaluation.rpo_hours)} "
        f"(max {evaluation.rpo_max_hours:.2f}h) -> {'ok' if evaluation.rpo_ok else 'fora da meta'}",
        "",
        "## Sub-checks (read-only no host restaurado)",
        "",
    ]
    for name in SUBCHECKS:
        lines.append(f"- {name}: {evaluation.subchecks[name]}")
    lines.extend(
        [
            "",
            "## Proximo passo",
            "",
            f"- alimente `python -m scripts.phase0_operational_report --restore {evaluation.verdict}`.",
            "",
            "## Sanitization",
            "",
            "- Este relatorio contem apenas timestamps, metas e status; sem nomes de "
            "snapshot, IPs, hostnames, usuarios, credenciais ou payloads.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate a Phase 0 timed-restore drill into sanitized evidence. "
            "Read-only: does not snapshot, restore or connect anywhere."
        )
    )
    parser.add_argument("--snapshot-timestamp", help="ISO-8601 horario do snapshot.")
    parser.add_argument("--restore-started-at", help="ISO-8601 inicio do restore.")
    parser.add_argument("--restore-finished-at", help="ISO-8601 fim do restore validado.")
    parser.add_argument(
        "--latest-data-timestamp",
        help="ISO-8601 do dado mais recente restaurado (para medir RPO).",
    )
    parser.add_argument("--rto-max-hours", type=float, default=DEFAULT_RTO_MAX_HOURS)
    parser.add_argument("--rpo-max-hours", type=float, default=DEFAULT_RPO_MAX_HOURS)
    for name in SUBCHECKS:
        parser.add_argument(f"--{name.replace('_', '-')}", choices=STATUSES, default="pending")
    parser.add_argument("--output", help="Escreve o relatorio num arquivo Markdown.")
    args = parser.parse_args()

    subchecks = {name: getattr(args, name) for name in SUBCHECKS}
    evaluation = evaluate_restore(
        snapshot_timestamp=parse_timestamp(args.snapshot_timestamp),
        restore_started_at=parse_timestamp(args.restore_started_at),
        restore_finished_at=parse_timestamp(args.restore_finished_at),
        latest_data_timestamp=parse_timestamp(args.latest_data_timestamp),
        subchecks=subchecks,
        rto_max_hours=args.rto_max_hours,
        rpo_max_hours=args.rpo_max_hours,
    )
    report = render_restore_report(evaluation)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0 if evaluation.verdict == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
