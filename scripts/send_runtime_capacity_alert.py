from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib import error, request

from scripts.check_runtime_capacity import Check, collect_checks, overall_status


DEFAULT_ALERT_PATH = "/webhooks/supportfaq-alerts"


@dataclass(frozen=True)
class AlertTarget:
    phone_e164: str
    chat_id: str


@dataclass(frozen=True)
class DeliveryResult:
    target_index: int
    ok: bool
    status: int | None
    error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send sanitized runtime capacity alerts through Hermes WhatsApp."
    )
    parser.add_argument("--path", default="/", help="Filesystem path to inspect.")
    parser.add_argument("--warning", type=float, default=75.0)
    parser.add_argument("--critical", type=float, default=85.0)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--alert-on",
        choices=("warning", "critical"),
        default="critical",
        help="Lowest status that sends WhatsApp alerts.",
    )
    parser.add_argument(
        "--force-test",
        action="store_true",
        help="Send a controlled test message even when capacity is healthy.",
    )
    parser.add_argument(
        "--recipients",
        default=os.getenv("HERMES_ALERT_RECIPIENTS", ""),
        help="Comma-separated E.164 phone numbers. Defaults to HERMES_ALERT_RECIPIENTS.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("HERMES_BASE_URL", ""),
        help="Hermes base URL. Defaults to HERMES_BASE_URL.",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.getenv("HERMES_ALERT_WEBHOOK_SECRET")
        or os.getenv("HERMES_WEBHOOK_SECRET", ""),
        help="Hermes alert secret. Defaults to HERMES_ALERT_WEBHOOK_SECRET or HERMES_WEBHOOK_SECRET.",
    )
    parser.add_argument(
        "--delivery-path",
        default=os.getenv("HERMES_ALERT_DELIVERY_PATH", DEFAULT_ALERT_PATH),
        help=f"Hermes alert path. Defaults to {DEFAULT_ALERT_PATH}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("HERMES_REQUEST_TIMEOUT_SECONDS", "5")),
    )
    parser.add_argument("--output", help="Write sanitized delivery report to a file.")
    args = parser.parse_args()

    checks = collect_checks(
        path=args.path,
        warning=args.warning,
        critical=args.critical,
        min_free_gb=args.min_free_gb,
        require_docker=False,
    )
    status = "test" if args.force_test else overall_status(checks)
    should_send = args.force_test or should_alert(status, args.alert_on)
    targets = parse_recipients(args.recipients)
    if should_send and not targets:
        print("capacity_alert_status=configuration_error missing_recipients", file=sys.stderr)
        return 2
    if should_send and (not args.base_url.strip() or not args.webhook_secret.strip()):
        print("capacity_alert_status=configuration_error missing_hermes_config", file=sys.stderr)
        return 2

    results: list[DeliveryResult] = []
    if should_send:
        message = build_alert_message(status=status, checks=checks, force_test=args.force_test)
        for index, target in enumerate(targets, start=1):
            results.append(
                deliver_alert(
                    base_url=args.base_url,
                    webhook_secret=args.webhook_secret,
                    delivery_path=args.delivery_path,
                    timeout_seconds=args.timeout_seconds,
                    target=target,
                    message=message,
                    delivery_id=f"supportfaq-capacity-{int(time.time())}-{index}",
                )
            )

    report = render_report(status=status, sent=should_send, checks=checks, results=results)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)
    if not should_send:
        return 0
    return 0 if all(result.ok for result in results) else 1


def should_alert(status: str, alert_on: str) -> bool:
    if alert_on == "critical":
        return status == "critical"
    return status in {"warning", "critical"}


def parse_recipients(raw: str) -> list[AlertTarget]:
    targets: list[AlertTarget] = []
    for value in raw.split(","):
        phone = value.strip()
        if not phone:
            continue
        digits = "".join(char for char in phone if char.isdigit())
        if not digits:
            continue
        normalized = f"+{digits}"
        targets.append(AlertTarget(phone_e164=normalized, chat_id=f"{digits}@s.whatsapp.net"))
    return targets


def build_alert_message(*, status: str, checks: list[Check], force_test: bool) -> str:
    disk = next((check for check in checks if check.name == "disk_capacity"), None)
    disk_detail = disk.detail if disk is not None else "disk_capacity=unavailable"
    prefix = "supportFAQ capacity alert TEST" if force_test else "supportFAQ capacity alert"
    return f"{prefix}: status={status} {disk_detail} action=check_vps_capacity"


def deliver_alert(
    *,
    base_url: str,
    webhook_secret: str,
    delivery_path: str,
    timeout_seconds: float,
    target: AlertTarget,
    message: str,
    delivery_id: str,
) -> DeliveryResult:
    payload = {
        "delivery_id": delivery_id,
        "channel": "whatsapp",
        "phone_e164": target.phone_e164,
        "chat_id": target.chat_id,
        "template": "runtime_capacity_alert",
        "variables": {"message": message},
    }
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    req = request.Request(
        f"{base_url.rstrip('/')}{delivery_path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Delivery-ID": delivery_id,
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": signature,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", response.getcode()))
            return DeliveryResult(target_index=0, ok=200 <= status < 300, status=status)
    except error.HTTPError as exc:
        return DeliveryResult(target_index=0, ok=False, status=exc.code, error="http_error")
    except (OSError, error.URLError):
        return DeliveryResult(target_index=0, ok=False, status=None, error="request_error")


def render_report(
    *,
    status: str,
    sent: bool,
    checks: list[Check],
    results: list[DeliveryResult],
) -> str:
    lines = [
        "# Runtime Capacity Alert",
        "",
        f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"- capacity_status: {status}",
        f"- sent: {str(sent).lower()}",
        f"- delivered: {sum(1 for result in results if result.ok)}/{len(results)}",
        "",
        "## Checks",
        "",
    ]
    for check in checks:
        lines.append(f"- {check.name}: status={check.status} detail={check.detail}")
    lines.extend(["", "## Deliveries", ""])
    if not results:
        lines.append("- none")
    for index, result in enumerate(results, start=1):
        lines.append(
            f"- target_{index}: ok={str(result.ok).lower()} status={result.status} error={result.error}"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Phone numbers, Hermes secrets, raw payloads and host details are not printed.",
            "- This command never prunes Docker data or modifies PostgreSQL volumes.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
