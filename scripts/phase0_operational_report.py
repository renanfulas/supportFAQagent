from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path


STATUSES = ("passed", "failed", "blocked", "pending")
REQUIRED_GATES = (
    "snapshot",
    "preflight",
    "migrations",
    "postgres_concurrency",
    "restore",
    "pgvector_gate",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized Phase 0 decision report.")
    for gate in REQUIRED_GATES:
        parser.add_argument(f"--{gate.replace('_', '-')}", choices=STATUSES, default="pending")
    parser.add_argument("--output", help="Write report to a Markdown file.")
    args = parser.parse_args()
    statuses = {gate: getattr(args, gate) for gate in REQUIRED_GATES}
    report = render_report(statuses)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0 if all(status == "passed" for status in statuses.values()) else 1


def render_report(statuses: dict[str, str]) -> str:
    invalid = set(statuses) - set(REQUIRED_GATES)
    if invalid or any(status not in STATUSES for status in statuses.values()):
        raise ValueError("invalid Phase 0 gate report")
    decision = "approved" if all(status == "passed" for status in statuses.values()) else "not_approved"
    lines = [
        "# Phase 0 Operational Decision",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- decision: {decision}",
        "",
        "## Gates",
        "",
    ]
    for gate in REQUIRED_GATES:
        lines.append(f"- {gate}: {statuses.get(gate, 'pending')}")
    lines.extend(
        [
            "",
            "## Sanitization",
            "",
            "- This report contains no secrets, URLs, IPs, hostnames, payloads or raw logs.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
