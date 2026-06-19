"""Build a sanitized activation evidence report for Meta WhatsApp/Hermes.

The script consumes sanitized outputs from the activation preflight and private
smoke commands. It extracts only readiness/check status and never copies raw
source report bodies into the final evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._:/ -]{1,80}$")
UNSAFE_LABEL_RE = re.compile(
    r"(sk-|secret|token|password|passwd|bearer|sha256=|\+[0-9]{8,}|[0-9]{12,})",
    re.IGNORECASE,
)
DEFAULT_REQUIRED_CHECKS = (
    "meta_webhook_verification",
    "meta_signed_status_webhook",
    "meta_chat_inbound_message",
    "meta_outbox_message_delivery",
    "meta_otp_delivery",
)
DEFAULT_REQUIRED_MODES = (
    "meta-webhook",
    "meta-chat",
    "meta-outbox-message",
    "meta-otp",
)


class ActivationEvidenceInputError(ValueError):
    """Raised when a sanitized evidence input cannot be read safely."""


@dataclass(frozen=True)
class PreflightMode:
    mode: str
    ready: bool
    missing: tuple[str, ...]
    invalid: tuple[str, ...]
    recommended_missing: tuple[str, ...]


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    ok: bool
    status: str
    error: str


@dataclass(frozen=True)
class ActivationEvidence:
    environment: str
    operator: str
    decision: str
    required_modes: tuple[str, ...]
    required_checks: tuple[str, ...]
    preflight_ready: bool | None
    preflight_modes: tuple[PreflightMode, ...]
    smoke_checks: tuple[SmokeCheck, ...]


def main() -> int:
    args = parse_args()
    try:
        evidence = build_evidence(
            environment=args.environment,
            operator=args.operator,
            decision=args.decision,
            required_modes=tuple(args.required_mode),
            required_checks=tuple(args.required_check),
            preflight_report=Path(args.preflight_report) if args.preflight_report else None,
            smoke_reports=tuple(Path(path) for path in args.smoke_report),
        )
    except ActivationEvidenceInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = render_evidence(evidence)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(report)
            output.write("\n")
    print(report)
    return 0 if evidence_is_ready(evidence) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate sanitized Meta/Hermes activation evidence.",
    )
    parser.add_argument("--environment", default="private-lab")
    parser.add_argument("--operator", default="unspecified")
    parser.add_argument(
        "--decision",
        choices=("pending", "promote", "rollback", "hold"),
        default="pending",
    )
    parser.add_argument(
        "--preflight-report",
        help="Path to JSON report from meta_whatsapp_activation_preflight.py --format json.",
    )
    parser.add_argument(
        "--smoke-report",
        action="append",
        default=[],
        help="Path to sanitized Markdown report from meta_whatsapp_private_smoke.py.",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        default=list(DEFAULT_REQUIRED_CHECKS),
        help="Smoke check required for promotion. Defaults to the full Meta activation gate.",
    )
    parser.add_argument(
        "--required-mode",
        action="append",
        default=list(DEFAULT_REQUIRED_MODES),
        help="Preflight mode required for promotion. Defaults to the full Meta activation gate.",
    )
    parser.add_argument("--output", help="Write sanitized activation evidence to this path.")
    return parser.parse_args()


def build_evidence(
    *,
    environment: str,
    operator: str,
    decision: str,
    preflight_report: Path | None,
    smoke_reports: tuple[Path, ...],
    required_modes: tuple[str, ...] = DEFAULT_REQUIRED_MODES,
    required_checks: tuple[str, ...] = DEFAULT_REQUIRED_CHECKS,
) -> ActivationEvidence:
    preflight_ready: bool | None = None
    preflight_modes: tuple[PreflightMode, ...] = ()
    if preflight_report is not None:
        preflight_ready, preflight_modes = parse_preflight_report(preflight_report)
    smoke_checks: list[SmokeCheck] = []
    for report_path in smoke_reports:
        smoke_checks.extend(parse_smoke_report(report_path))
    return ActivationEvidence(
        environment=safe_label(environment),
        operator=safe_label(operator),
        decision=decision,
        required_modes=tuple(safe_label(mode) for mode in required_modes),
        required_checks=tuple(safe_label(check) for check in required_checks),
        preflight_ready=preflight_ready,
        preflight_modes=preflight_modes,
        smoke_checks=tuple(smoke_checks),
    )


def parse_preflight_report(path: Path) -> tuple[bool, tuple[PreflightMode, ...]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ActivationEvidenceInputError(
            f"Preflight report not found: {safe_label(str(path))}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ActivationEvidenceInputError(
            f"Preflight report is not valid JSON: {safe_label(str(path))}"
        ) from exc
    modes: list[PreflightMode] = []
    for raw_mode in payload.get("modes", []):
        if not isinstance(raw_mode, dict):
            continue
        modes.append(
            PreflightMode(
                mode=safe_label(str(raw_mode.get("mode", "unknown"))),
                ready=bool(raw_mode.get("ready")),
                missing=tuple(safe_name(name) for name in raw_mode.get("missing", [])),
                invalid=tuple(safe_name(name) for name in raw_mode.get("invalid", [])),
                recommended_missing=tuple(
                    safe_name(name) for name in raw_mode.get("recommended_missing", [])
                ),
            )
        )
    return bool(payload.get("ready")), tuple(modes)


def parse_smoke_report(path: Path) -> tuple[SmokeCheck, ...]:
    checks: list[SmokeCheck] = []
    current: dict[str, str] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ActivationEvidenceInputError(
            f"Smoke report not found: {safe_label(str(path))}"
        ) from exc
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("### "):
            if current:
                checks.append(make_smoke_check(current))
            current = {"name": safe_label(line.removeprefix("### ").strip())}
            continue
        if current is None:
            continue
        if line.startswith("- ok:"):
            current["ok"] = line.split(":", 1)[1].strip()
        elif line.startswith("- status:"):
            current["status"] = safe_label(line.split(":", 1)[1].strip())
        elif line.startswith("- error:"):
            current["error"] = safe_label(line.split(":", 1)[1].strip())
    if current:
        checks.append(make_smoke_check(current))
    return tuple(checks)


def make_smoke_check(raw: dict[str, str]) -> SmokeCheck:
    return SmokeCheck(
        name=safe_label(raw.get("name", "unknown")),
        ok=raw.get("ok", "").lower() == "true",
        status=safe_label(raw.get("status", "unknown")),
        error=safe_label(raw.get("error", "none")),
    )


def render_evidence(evidence: ActivationEvidence) -> str:
    lines = [
        "# Meta/Hermes Activation Evidence",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- environment: {evidence.environment}",
        f"- operator: {evidence.operator}",
        f"- decision: {evidence.decision}",
        f"- ready_for_promotion: {str(evidence_is_ready(evidence)).lower()}",
        "",
        "## Preflight",
        "",
    ]
    if evidence.preflight_ready is None:
        lines.append("- report: missing")
    else:
        lines.append(f"- ready: {str(evidence.preflight_ready).lower()}")
        for mode in evidence.preflight_modes:
            lines.extend(
                [
                    "",
                    f"### {mode.mode}",
                    "",
                    f"- ready: {str(mode.ready).lower()}",
                    f"- missing: {format_names(mode.missing)}",
                    f"- invalid: {format_names(mode.invalid)}",
                    f"- recommended_missing: {format_names(mode.recommended_missing)}",
                ]
            )
    lines.extend(["", "## Smoke", ""])
    if not evidence.smoke_checks:
        lines.append("- report: missing")
    for check in evidence.smoke_checks:
        lines.extend(
            [
                f"### {check.name}",
                "",
                f"- ok: {str(check.ok).lower()}",
                f"- status: {check.status}",
                f"- error: {check.error}",
                "",
            ]
        )
    gate = promotion_gate_status(evidence)
    lines.extend(
        [
            "## Promotion Gate",
            "",
            "- Required preflight modes must be ready.",
            f"- required_modes: {format_names(evidence.required_modes)}",
            f"- missing_required_modes: {format_names(gate['missing_required_modes'])}",
            f"- failed_required_modes: {format_names(gate['failed_required_modes'])}",
            f"- required_checks: {format_names(evidence.required_checks)}",
            f"- missing_required_checks: {format_names(gate['missing_required_checks'])}",
            f"- failed_required_checks: {format_names(gate['failed_required_checks'])}",
            "- Every required preflight mode must be present and ready.",
            "- Every required smoke check must be present and ok.",
            "- Backend and provider logs must be reviewed separately for absence of PII/secrets.",
            "- Rollback env vars must be confirmed before promotion.",
            "",
            "## Sanitization",
            "",
            "- This report contains only labels, booleans, status codes and variable names.",
            "- Source report bodies, secrets, tokens, webhook URLs, payloads, phone numbers and OTP codes are not copied.",
        ]
    )
    return "\n".join(lines)


def evidence_is_ready(evidence: ActivationEvidence) -> bool:
    gate = promotion_gate_status(evidence)
    return (
        evidence.preflight_ready is not None
        and bool(evidence.smoke_checks)
        and not gate["missing_required_modes"]
        and not gate["failed_required_modes"]
        and not gate["missing_required_checks"]
        and not gate["failed_required_checks"]
        and evidence.decision == "promote"
    )


def promotion_gate_status(evidence: ActivationEvidence) -> dict[str, tuple[str, ...]]:
    modes_by_name = {mode.mode: mode for mode in evidence.preflight_modes}
    checks_by_name = {check.name: check for check in evidence.smoke_checks}
    missing_modes = tuple(
        mode_name
        for mode_name in evidence.required_modes
        if mode_name not in modes_by_name
    )
    failed_modes = tuple(
        mode_name
        for mode_name in evidence.required_modes
        if mode_name in modes_by_name and not modes_by_name[mode_name].ready
    )
    missing_checks = tuple(
        check_name
        for check_name in evidence.required_checks
        if check_name not in checks_by_name
    )
    failed_checks = tuple(
        check_name
        for check_name in evidence.required_checks
        if check_name in checks_by_name and not checks_by_name[check_name].ok
    )
    return {
        "missing_required_modes": missing_modes,
        "failed_required_modes": failed_modes,
        "missing_required_checks": missing_checks,
        "failed_required_checks": failed_checks,
    }


def safe_name(value: Any) -> str:
    text = str(value).strip()
    if re.fullmatch(r"[A-Z0-9_]{1,80}", text):
        return text
    return "REDACTED_NAME"


def safe_label(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "none"
    if not SAFE_LABEL_RE.fullmatch(text) or UNSAFE_LABEL_RE.search(text):
        return "redacted"
    return text


def format_names(names: tuple[str, ...]) -> str:
    return ", ".join(names) if names else "none"


if __name__ == "__main__":
    raise SystemExit(main())
