"""Run the sanitized Meta/Hermes activation workflow.

The suite always writes a preflight report and activation evidence. It runs
private smoke checks only when explicitly requested. Some smoke checks can send
real WhatsApp messages and must be used only with lab numbers.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import meta_whatsapp_activation_evidence as evidence
from scripts import meta_whatsapp_activation_preflight as preflight
from scripts import meta_whatsapp_private_smoke as smoke


@dataclass(frozen=True)
class SuiteResult:
    output_dir: Path
    preflight_report: Path
    smoke_report: Path | None
    evidence_report: Path
    evidence_ready: bool
    smoke_passed: bool


def main() -> int:
    args = parse_args()
    try:
        result = run_suite(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(render_summary(result))
    if args.decision == "promote":
        return 0 if result.evidence_ready else 1
    if result.smoke_report is not None and not result.smoke_passed:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run sanitized Meta/Hermes activation preflight, selected smokes and evidence.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--environment", default="private-lab")
    parser.add_argument("--operator", default="unspecified")
    parser.add_argument(
        "--decision",
        choices=("pending", "promote", "rollback", "hold"),
        default="pending",
    )
    parser.add_argument("--meta-webhook", action="store_true")
    parser.add_argument("--meta-chat-inbound", action="store_true")
    parser.add_argument("--meta-chat-from")
    parser.add_argument("--meta-chat-text", default="supportFAQagent private inbound smoke")
    parser.add_argument("--meta-outbox-message", action="store_true")
    parser.add_argument("--meta-outbox-to")
    parser.add_argument("--meta-outbox-text", default="supportFAQagent private smoke")
    parser.add_argument("--meta-otp", action="store_true")
    parser.add_argument("--meta-otp-phone")
    parser.add_argument("--meta-otp-code", default="000000")
    parser.add_argument("--meta-otp-expires-seconds", type=int, default=300)
    parser.add_argument("--hermes-otp", action="store_true")
    parser.add_argument("--hermes-phone")
    return parser.parse_args()


def run_suite(args: argparse.Namespace) -> SuiteResult:
    validate_selected_smoke_recipients(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = output_dir / "meta-whatsapp-preflight.json"
    smoke_report = output_dir / "meta-whatsapp-smoke.md"
    evidence_report = output_dir / "meta-whatsapp-activation-evidence.md"

    preflight_results = [
        preflight.evaluate_mode(mode, os.environ)
        for mode in preflight.MODE_REQUIREMENTS
    ]
    preflight_report.write_text(
        preflight.render_report(preflight_results, output_format="json") + "\n",
        encoding="utf-8",
    )

    smoke_results = selected_smoke_results(args)
    written_smoke_report: Path | None = None
    if smoke_results:
        smoke_report.write_text(smoke.render_report(smoke_results) + "\n", encoding="utf-8")
        written_smoke_report = smoke_report

    activation_evidence = evidence.build_evidence(
        environment=args.environment,
        operator=args.operator,
        decision=args.decision,
        preflight_report=preflight_report,
        smoke_reports=(smoke_report,) if written_smoke_report else (),
    )
    evidence_report.write_text(evidence.render_evidence(activation_evidence) + "\n", encoding="utf-8")
    return SuiteResult(
        output_dir=output_dir,
        preflight_report=preflight_report,
        smoke_report=written_smoke_report,
        evidence_report=evidence_report,
        evidence_ready=evidence.evidence_is_ready(activation_evidence),
        smoke_passed=all(result.ok for result in smoke_results),
    )


def selected_smoke_results(args: argparse.Namespace) -> list[smoke.CheckResult]:
    results: list[smoke.CheckResult] = []
    if args.meta_webhook:
        require_env("META_WHATSAPP_APP_SECRET", "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN")
        results.append(
            smoke.smoke_meta_webhook_verification(
                base_url=args.base_url,
                verify_token=os.environ["META_WHATSAPP_WEBHOOK_VERIFY_TOKEN"],
                challenge="private-suite-challenge",
            )
        )
        results.append(
            smoke.smoke_meta_signed_status_webhook(
                base_url=args.base_url,
                app_secret=os.environ["META_WHATSAPP_APP_SECRET"],
            )
        )
    if args.meta_chat_inbound:
        require_env("META_WHATSAPP_APP_SECRET")
        if not args.meta_chat_from:
            raise ValueError("--meta-chat-from is required with --meta-chat-inbound")
        results.append(
            smoke.smoke_meta_chat_inbound_message(
                base_url=args.base_url,
                app_secret=os.environ["META_WHATSAPP_APP_SECRET"],
                from_wa_id=args.meta_chat_from,
                text=args.meta_chat_text,
            )
        )
    if args.meta_outbox_message:
        require_env(
            "META_WHATSAPP_ACCESS_TOKEN",
            "META_WHATSAPP_PHONE_NUMBER_ID",
            "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
        )
        if os.environ["OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT"].strip().lower() != "meta_whatsapp":
            raise ValueError(
                "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT must be meta_whatsapp",
            )
        if not args.meta_outbox_to:
            raise ValueError("--meta-outbox-to is required with --meta-outbox-message")
        results.append(
            smoke.smoke_meta_outbox_message_delivery(
                to=args.meta_outbox_to,
                text=args.meta_outbox_text,
            )
        )
    if args.meta_otp:
        require_env(
            "META_WHATSAPP_ACCESS_TOKEN",
            "META_WHATSAPP_PHONE_NUMBER_ID",
            "META_WHATSAPP_OTP_TEMPLATE_NAME",
        )
        if not args.meta_otp_phone:
            raise ValueError("--meta-otp-phone is required with --meta-otp")
        results.append(
            smoke.smoke_meta_otp_delivery(
                phone=args.meta_otp_phone,
                code=args.meta_otp_code,
                expires_in_seconds=args.meta_otp_expires_seconds,
            )
        )
    if args.hermes_otp:
        require_env("HERMES_BASE_URL", "HERMES_WEBHOOK_SECRET")
        if not args.hermes_phone:
            raise ValueError("--hermes-phone is required with --hermes-otp")
        results.append(
            smoke.smoke_hermes_otp_delivery(
                base_url=os.environ["HERMES_BASE_URL"],
                webhook_secret=os.environ["HERMES_WEBHOOK_SECRET"],
                path=os.getenv("HERMES_OTP_DELIVERY_PATH", "/otp-delivery"),
                phone=args.hermes_phone,
            )
        )
    return results


def validate_selected_smoke_recipients(args: argparse.Namespace) -> None:
    if args.meta_chat_inbound and not args.meta_chat_from:
        raise ValueError("--meta-chat-from is required with --meta-chat-inbound")
    if args.meta_outbox_message and not args.meta_outbox_to:
        raise ValueError("--meta-outbox-to is required with --meta-outbox-message")
    if args.meta_otp and not args.meta_otp_phone:
        raise ValueError("--meta-otp-phone is required with --meta-otp")
    if args.hermes_otp and not args.hermes_phone:
        raise ValueError("--hermes-phone is required with --hermes-otp")


def require_env(*names: str) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing required env: {', '.join(missing)}")


def render_summary(result: SuiteResult) -> str:
    lines = [
        "Meta/Hermes activation suite completed",
        f"- output_dir: {safe_display_path(result.output_dir)}",
        f"- preflight_report: {safe_display_path(result.preflight_report)}",
        f"- smoke_report: {safe_display_path(result.smoke_report) if result.smoke_report else 'not_run'}",
        f"- evidence_report: {safe_display_path(result.evidence_report)}",
        f"- smoke_passed: {str(result.smoke_passed).lower()}",
        f"- evidence_ready: {str(result.evidence_ready).lower()}",
        "- values: sanitized",
    ]
    return "\n".join(lines)


def safe_display_path(path: Path) -> str:
    label = str(path)
    return label if evidence.safe_label(label) == label else "redacted-path"


if __name__ == "__main__":
    raise SystemExit(main())
