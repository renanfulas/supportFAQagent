"""Sanitized readiness preflight for Meta WhatsApp and Hermes activation.

This command checks whether the environment has the minimum configuration for
each activation mode. It never prints configured values.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
import sys
from typing import Mapping


COMMON_WEB_AUTH_REQUIREMENTS = (
    "ENABLE_WEB_WHATSAPP_AUTH",
    "IDENTITY_HASH_SECRET",
    "OTP_DIGEST_SECRET",
)

MODE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "meta-webhook": (
        "ENABLE_META_WHATSAPP_WEBHOOK",
        "META_WHATSAPP_APP_SECRET",
        "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    ),
    "meta-chat": (
        "ENABLE_META_WHATSAPP_WEBHOOK",
        "ENABLE_META_WHATSAPP_CHAT",
        "META_WHATSAPP_APP_SECRET",
        "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    ),
    "meta-outbox-message": (
        "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT",
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    ),
    "meta-otp": (
        *COMMON_WEB_AUTH_REQUIREMENTS,
        "WEB_AUTH_OTP_DELIVERY_TRANSPORT",
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
        "META_WHATSAPP_OTP_TEMPLATE_NAME",
    ),
    "hermes-otp": (
        *COMMON_WEB_AUTH_REQUIREMENTS,
        "WEB_AUTH_OTP_DELIVERY_TRANSPORT",
        "HERMES_BASE_URL",
        "HERMES_WEBHOOK_SECRET",
    ),
}


EXPECTED_VALUES: dict[str, dict[str, str]] = {
    "meta-webhook": {"ENABLE_META_WHATSAPP_WEBHOOK": "true"},
    "meta-chat": {
        "ENABLE_META_WHATSAPP_WEBHOOK": "true",
        "ENABLE_META_WHATSAPP_CHAT": "true",
    },
    "meta-outbox-message": {
        "OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT": "meta_whatsapp",
    },
    "meta-otp": {
        "ENABLE_WEB_WHATSAPP_AUTH": "true",
        "WEB_AUTH_OTP_DELIVERY_TRANSPORT": "meta",
    },
    "hermes-otp": {
        "ENABLE_WEB_WHATSAPP_AUTH": "true",
        "WEB_AUTH_OTP_DELIVERY_TRANSPORT": "hermes",
    },
}


OPTIONAL_RECOMMENDED: dict[str, tuple[str, ...]] = {
    "meta-chat": ("META_WHATSAPP_GRAPH_API_VERSION",),
    "meta-outbox-message": ("META_WHATSAPP_GRAPH_API_VERSION",),
    "meta-otp": ("META_WHATSAPP_OTP_TEMPLATE_LANGUAGE",),
    "hermes-otp": ("HERMES_OTP_DELIVERY_PATH",),
}


@dataclass(frozen=True)
class ModeReadiness:
    mode: str
    ready: bool
    present: tuple[str, ...]
    missing: tuple[str, ...]
    invalid: tuple[str, ...]
    recommended_missing: tuple[str, ...]


def main() -> int:
    args = parse_args()
    modes = tuple(MODE_REQUIREMENTS) if args.mode == "all" else (args.mode,)
    results = [evaluate_mode(mode, os.environ) for mode in modes]
    report = render_report(results, output_format=args.format)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(report)
            output.write("\n")
    print(report)
    return 0 if all(result.ready for result in results) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check sanitized activation readiness for Meta WhatsApp and Hermes.",
    )
    parser.add_argument(
        "--mode",
        choices=(*MODE_REQUIREMENTS.keys(), "all"),
        default="all",
        help="Activation mode to validate.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Values are never printed.",
    )
    parser.add_argument("--output", help="Write the sanitized report to this path.")
    return parser.parse_args()


def evaluate_mode(mode: str, env: Mapping[str, str]) -> ModeReadiness:
    requirements = MODE_REQUIREMENTS[mode]
    expected_values = EXPECTED_VALUES.get(mode, {})
    present: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for name in requirements:
        value = env.get(name, "").strip()
        if not value:
            missing.append(name)
            continue
        expected_value = expected_values.get(name)
        if expected_value is not None and value.lower() != expected_value:
            invalid.append(name)
            continue
        present.append(name)

    recommended_missing = tuple(
        name
        for name in OPTIONAL_RECOMMENDED.get(mode, ())
        if not env.get(name, "").strip()
    )
    return ModeReadiness(
        mode=mode,
        ready=not missing and not invalid,
        present=tuple(present),
        missing=tuple(missing),
        invalid=tuple(invalid),
        recommended_missing=recommended_missing,
    )


def render_report(results: list[ModeReadiness], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "ready": all(result.ready for result in results),
                "modes": [
                    {
                        "mode": result.mode,
                        "ready": result.ready,
                        "present": list(result.present),
                        "missing": list(result.missing),
                        "invalid": list(result.invalid),
                        "recommended_missing": list(result.recommended_missing),
                    }
                    for result in results
                ],
                "sanitization": "Only variable names and readiness booleans are printed.",
            },
            ensure_ascii=True,
            indent=2,
        )

    lines = [
        "# Meta WhatsApp Activation Preflight",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- ready: {str(all(result.ready for result in results)).lower()}",
        "",
        "## Modes",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.mode}",
                "",
                f"- ready: {str(result.ready).lower()}",
                f"- present: {format_names(result.present)}",
                f"- missing: {format_names(result.missing)}",
                f"- invalid: {format_names(result.invalid)}",
                f"- recommended_missing: {format_names(result.recommended_missing)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Sanitization",
            "",
            "- Only variable names and readiness booleans are printed.",
            "- Secrets, tokens, webhook URLs, phone numbers, OTP codes and provider responses are never printed.",
        ],
    )
    return "\n".join(lines)


def format_names(names: tuple[str, ...]) -> str:
    return ", ".join(names) if names else "none"


if __name__ == "__main__":
    raise SystemExit(main())
