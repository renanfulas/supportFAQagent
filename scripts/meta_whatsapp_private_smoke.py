"""Private Meta/Hermes smoke checks with sanitized output.

The default checks do not send WhatsApp messages. They validate the Meta webhook
verification path and a signed status-only webhook payload. Hermes delivery,
Meta outbox delivery and Meta inbound chat are checked only when explicitly
requested because they may trigger an external send.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.otp_delivery import MetaWhatsAppOtpDeliveryAdapter
from app.web_auth.delivery import OtpDeliveryUnavailable
from app.web_auth.models import OtpDeliveryRequest
from scripts.dispatch_outbox import PermanentDeliveryError, deliver


DEFAULT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    status: int | None
    latency_ms: float
    summary: dict[str, Any]
    error: str | None = None


def main() -> int:
    args = parse_args()
    recipient_error = validate_requested_recipients(args)
    if recipient_error:
        print(recipient_error, file=sys.stderr)
        return 2
    results: list[CheckResult] = []
    if args.meta_webhook:
        missing = missing_env("META_WHATSAPP_APP_SECRET", "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN")
        if missing:
            print(f"Missing required env for Meta webhook smoke: {', '.join(missing)}", file=sys.stderr)
            return 2
        results.append(
            smoke_meta_webhook_verification(
                base_url=args.base_url,
                verify_token=os.environ["META_WHATSAPP_WEBHOOK_VERIFY_TOKEN"],
                challenge=args.challenge,
            )
        )
        results.append(
            smoke_meta_signed_status_webhook(
                base_url=args.base_url,
                app_secret=os.environ["META_WHATSAPP_APP_SECRET"],
            )
        )
    if args.meta_otp:
        missing = missing_env(
            "META_WHATSAPP_ACCESS_TOKEN",
            "META_WHATSAPP_PHONE_NUMBER_ID",
            "META_WHATSAPP_OTP_TEMPLATE_NAME",
        )
        if missing:
            print(f"Missing required env for Meta OTP smoke: {', '.join(missing)}", file=sys.stderr)
            return 2
        if not args.meta_otp_phone:
            print("--meta-otp-phone is required with --meta-otp", file=sys.stderr)
            return 2
        results.append(
            smoke_meta_otp_delivery(
                phone=args.meta_otp_phone,
                code=args.meta_otp_code,
                expires_in_seconds=args.meta_otp_expires_seconds,
            )
        )
    if args.hermes_otp:
        missing = missing_env("HERMES_BASE_URL", "HERMES_WEBHOOK_SECRET")
        if missing:
            print(f"Missing required env for Hermes smoke: {', '.join(missing)}", file=sys.stderr)
            return 2
        if not args.hermes_phone:
            print("--hermes-phone is required with --hermes-otp", file=sys.stderr)
            return 2
        results.append(
            smoke_hermes_otp_delivery(
                base_url=os.environ["HERMES_BASE_URL"],
                webhook_secret=os.environ["HERMES_WEBHOOK_SECRET"],
                path=os.getenv("HERMES_OTP_DELIVERY_PATH", "/otp-delivery"),
                phone=args.hermes_phone,
            )
        )
    if args.meta_outbox_message:
        missing = missing_env(
            "META_WHATSAPP_ACCESS_TOKEN",
            "META_WHATSAPP_PHONE_NUMBER_ID",
            "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
        )
        if missing:
            print(
                f"Missing required env for Meta outbox smoke: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        if os.environ["OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT"].strip().lower() != "meta_whatsapp":
            print(
                "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT must be meta_whatsapp for Meta outbox smoke",
                file=sys.stderr,
            )
            return 2
        if not args.meta_outbox_to:
            print("--meta-outbox-to is required with --meta-outbox-message", file=sys.stderr)
            return 2
        results.append(
            smoke_meta_outbox_message_delivery(
                to=args.meta_outbox_to,
                text=args.meta_outbox_text,
            )
        )
    if args.meta_chat_inbound:
        missing = missing_env("META_WHATSAPP_APP_SECRET")
        if missing:
            print(
                f"Missing required env for Meta chat inbound smoke: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        if not args.meta_chat_from:
            print("--meta-chat-from is required with --meta-chat-inbound", file=sys.stderr)
            return 2
        results.append(
            smoke_meta_chat_inbound_message(
                base_url=args.base_url,
                app_secret=os.environ["META_WHATSAPP_APP_SECRET"],
                from_wa_id=args.meta_chat_from,
                text=args.meta_chat_text,
            )
        )
    if not results:
        print(
            "Choose at least one smoke target: --meta-webhook, --meta-otp, --hermes-otp, --meta-outbox-message or --meta-chat-inbound",
            file=sys.stderr,
        )
        return 2

    report = render_report(results)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(report)
            output.write("\n")
    print(report)
    return 0 if all(result.ok for result in results) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run private Meta/Hermes smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--meta-webhook", action="store_true")
    parser.add_argument("--challenge", default="private-smoke-challenge")
    parser.add_argument(
        "--hermes-otp",
        action="store_true",
        help="Actually POST an OTP delivery payload to Hermes. Use only in private lab.",
    )
    parser.add_argument(
        "--meta-otp",
        action="store_true",
        help="Actually send an OTP template via Meta. Use only in private lab.",
    )
    parser.add_argument(
        "--meta-otp-phone",
        help="Lab WhatsApp recipient used only when --meta-otp is set.",
    )
    parser.add_argument(
        "--meta-otp-code",
        default="000000",
        help="OTP code used only when --meta-otp is set.",
    )
    parser.add_argument(
        "--meta-otp-expires-seconds",
        type=int,
        default=300,
        help="OTP expiry used only when --meta-otp is set.",
    )
    parser.add_argument(
        "--hermes-phone",
        help="Phone used only when --hermes-otp is explicitly set.",
    )
    parser.add_argument(
        "--meta-outbox-message",
        action="store_true",
        help="Actually send a WhatsApp text via dispatcher Meta transport. Use only in private lab.",
    )
    parser.add_argument(
        "--meta-outbox-to",
        help="Lab WhatsApp recipient used only when --meta-outbox-message is set.",
    )
    parser.add_argument(
        "--meta-outbox-text",
        default="supportFAQagent private smoke",
        help="Safe text used only when --meta-outbox-message is set.",
    )
    parser.add_argument(
        "--meta-chat-inbound",
        action="store_true",
        help="POST a signed inbound text webhook. May trigger a real Meta reply when chat is enabled.",
    )
    parser.add_argument(
        "--meta-chat-from",
        help="Lab WhatsApp sender wa_id used only when --meta-chat-inbound is set.",
    )
    parser.add_argument(
        "--meta-chat-text",
        default="supportFAQagent private inbound smoke",
        help="Safe inbound text used only when --meta-chat-inbound is set.",
    )
    parser.add_argument("--output", help="Write sanitized Markdown report to this path.")
    return parser.parse_args()


def smoke_meta_webhook_verification(
    *,
    base_url: str,
    verify_token: str,
    challenge: str,
) -> CheckResult:
    started_at = time.perf_counter()
    query = urlencode(
        {
            "hub.mode": "subscribe",
            "hub.verify_token": verify_token,
            "hub.challenge": challenge,
        }
    )
    url = f"{base_url.rstrip('/')}/integrations/meta/whatsapp/webhook?{query}"
    status, body, error = request_text("GET", url)
    ok = status == 200 and body == challenge
    return CheckResult(
        name="meta_webhook_verification",
        ok=ok,
        status=status,
        latency_ms=elapsed_ms(started_at),
        summary={"challenge_echoed": body == challenge},
        error=error,
    )


def smoke_meta_signed_status_webhook(*, base_url: str, app_secret: str) -> CheckResult:
    started_at = time.perf_counter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.private-smoke",
                                    "status": "sent",
                                    "timestamp": "1710000000",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    status, response, error = request_json(
        "POST",
        f"{base_url.rstrip('/')}/integrations/meta/whatsapp/webhook",
        headers={"X-Hub-Signature-256": meta_signature(body, app_secret)},
        body=body,
    )
    ok = status == 200 and response.get("status") == "accepted"
    return CheckResult(
        name="meta_signed_status_webhook",
        ok=ok,
        status=status,
        latency_ms=elapsed_ms(started_at),
        summary={"accepted": response.get("status") == "accepted"},
        error=error,
    )


def smoke_meta_chat_inbound_message(
    *,
    base_url: str,
    app_secret: str,
    from_wa_id: str,
    text: str,
) -> CheckResult:
    started_at = time.perf_counter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": from_wa_id,
                                    "id": "wamid.private-inbound-smoke",
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    status, response, error = request_json(
        "POST",
        f"{base_url.rstrip('/')}/integrations/meta/whatsapp/webhook",
        headers={"X-Hub-Signature-256": meta_signature(body, app_secret)},
        body=body,
    )
    ok = status == 200 and response.get("status") == "accepted"
    return CheckResult(
        name="meta_chat_inbound_message",
        ok=ok,
        status=status,
        latency_ms=elapsed_ms(started_at),
        summary={"accepted": response.get("status") == "accepted"},
        error=error,
    )


def smoke_hermes_otp_delivery(
    *,
    base_url: str,
    webhook_secret: str,
    path: str,
    phone: str,
) -> CheckResult:
    started_at = time.perf_counter()
    chat_id = f"{''.join(char for char in phone if char.isdigit())}@s.whatsapp.net"
    payload = {
        "delivery_id": "private-smoke-delivery",
        "channel": "whatsapp",
        "phone_e164": phone,
        "chat_id": chat_id,
        "template": "web_login_otp",
        "variables": {"code": "000000", "expires_in_minutes": 5},
    }
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    status, response, error = request_json(
        "POST",
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Content-Type": "application/json",
            "X-Delivery-ID": "private-smoke-delivery",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": f"sha256={signature}",
        },
        body=body,
    )
    return CheckResult(
        name="hermes_otp_delivery",
        ok=status is not None and 200 <= status < 300,
        status=status,
        latency_ms=elapsed_ms(started_at),
        summary={"accepted": status is not None and 200 <= status < 300},
        error=error,
    )


def smoke_meta_otp_delivery(
    *,
    phone: str,
    code: str,
    expires_in_seconds: int,
) -> CheckResult:
    started_at = time.perf_counter()
    adapter = MetaWhatsAppOtpDeliveryAdapter(
        client=MetaWhatsAppClient(
            access_token=os.environ["META_WHATSAPP_ACCESS_TOKEN"],
            phone_number_id=os.environ["META_WHATSAPP_PHONE_NUMBER_ID"],
            graph_api_version=os.getenv("META_WHATSAPP_GRAPH_API_VERSION", "v25.0"),
            timeout_seconds=int(os.getenv("META_WHATSAPP_REQUEST_TIMEOUT_SECONDS", "5")),
        ),
        template_name=os.environ["META_WHATSAPP_OTP_TEMPLATE_NAME"],
        language_code=os.getenv("META_WHATSAPP_OTP_TEMPLATE_LANGUAGE", "pt_BR"),
    )
    try:
        adapter.deliver(
            OtpDeliveryRequest(
                challenge_id="private-smoke-meta-otp",
                phone=phone,
                code=code,
                expires_in_seconds=expires_in_seconds,
            )
        )
    except (OtpDeliveryUnavailable, ValueError, RuntimeError) as exc:
        return CheckResult(
            name="meta_otp_delivery",
            ok=False,
            status=None,
            latency_ms=elapsed_ms(started_at),
            summary={"sent": False},
            error=sanitize_error(exc),
        )
    return CheckResult(
        name="meta_otp_delivery",
        ok=True,
        status=None,
        latency_ms=elapsed_ms(started_at),
        summary={"sent": True},
    )


def smoke_meta_outbox_message_delivery(*, to: str, text: str) -> CheckResult:
    started_at = time.perf_counter()
    try:
        deliver(
            {
                "event_type": "whatsapp.message.requested",
                "request_id": "private-smoke-meta-outbox",
                "idempotency_key": "whatsapp:private-smoke-meta-outbox",
                "payload_sanitized": {"to": to, "text": text},
            }
        )
    except PermanentDeliveryError as exc:
        return CheckResult(
            name="meta_outbox_message_delivery",
            ok=False,
            status=None,
            latency_ms=elapsed_ms(started_at),
            summary={"sent": False},
            error=sanitize_error(exc),
        )
    except Exception as exc:
        return CheckResult(
            name="meta_outbox_message_delivery",
            ok=False,
            status=None,
            latency_ms=elapsed_ms(started_at),
            summary={"sent": False},
            error=sanitize_error(exc),
        )
    return CheckResult(
        name="meta_outbox_message_delivery",
        ok=True,
        status=None,
        latency_ms=elapsed_ms(started_at),
        summary={"sent": True},
    )


def request_text(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, str, str | None]:
    request = Request(url, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8"), None
    except HTTPError as exc:
        return exc.code, "", f"http_error:{exc.code}"
    except URLError as exc:
        return None, "", f"url_error:{exc.reason}"
    except TimeoutError:
        return None, "", "timeout"


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int | None, dict[str, Any], str | None]:
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.status, parse_json(response.read().decode("utf-8")), None
    except HTTPError as exc:
        return exc.code, parse_json(exc.read().decode("utf-8", errors="replace")), f"http_error:{exc.code}"
    except URLError as exc:
        return None, {}, f"url_error:{exc.reason}"
    except TimeoutError:
        return None, {}, "timeout"


def meta_signature(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def parse_json(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def missing_env(*names: str) -> list[str]:
    return [name for name in names if not os.getenv(name)]


def validate_requested_recipients(args: argparse.Namespace) -> str | None:
    if args.meta_otp and not args.meta_otp_phone:
        return "--meta-otp-phone is required with --meta-otp"
    if args.hermes_otp and not args.hermes_phone:
        return "--hermes-phone is required with --hermes-otp"
    if args.meta_outbox_message and not args.meta_outbox_to:
        return "--meta-outbox-to is required with --meta-outbox-message"
    if args.meta_chat_inbound and not args.meta_chat_from:
        return "--meta-chat-from is required with --meta-chat-inbound"
    return None


def sanitize_error(exc: Exception) -> str:
    message = str(exc)
    if not message:
        return type(exc).__name__
    if any(marker in message.lower() for marker in ("token", "secret", "bearer", "+")):
        return type(exc).__name__
    if len(message) > 120:
        return type(exc).__name__
    return message


def render_report(results: list[CheckResult]) -> str:
    lines = [
        "# Meta/Hermes Private Smoke Report",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- passed: {sum(result.ok for result in results)}/{len(results)}",
        "",
        "## Checks",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                "",
                f"- ok: {str(result.ok).lower()}",
                f"- status: {result.status}",
                f"- latency_ms: {result.latency_ms}",
                f"- error: {result.error}",
                "- summary:",
            ]
        )
        for key, value in result.summary.items():
            lines.append(f"  - {key}: {json.dumps(value, ensure_ascii=True)}")
        lines.append("")
    lines.extend(
        [
            "## Sanitization",
            "",
            "- Secrets, raw headers, raw payloads, OTP codes, phone numbers and provider responses are not printed.",
            "- Hermes OTP, Meta OTP, Meta outbox and Meta inbound chat smoke may send real deliveries and must be run only in a private lab.",
        ]
    )
    return "\n".join(lines)


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
