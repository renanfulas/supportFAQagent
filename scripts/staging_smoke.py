"""HTTP smoke test for staging/runtime validation.

The script avoids printing secrets, raw headers, full answers, or raw payloads.
It is intended for private staging runs after updating the runtime to main.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_DOMAIN = "suporte-vps-whatsapp"
DEFAULT_MESSAGE = "Como conectar o WhatsApp com a Evolution API na VPS?"
DEFAULT_SESSION_ID = "smoke:staging"
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class SmokeResult:
    name: str
    ok: bool
    status: int | None
    latency_ms: float
    summary: dict[str, Any]
    error: str | None = None


def main() -> int:
    args = parse_args()
    api_key = args.api_key or os.getenv("API_SECRET_KEY") or os.getenv("X_API_KEY")
    if not api_key:
        print("Missing API key. Set API_SECRET_KEY or pass --api-key.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    request_id = args.request_id or f"smoke-{uuid4()}"

    results = [
        smoke_health(base_url),
        smoke_domains(base_url, api_key, request_id, args.domain),
        smoke_chat(
            base_url=base_url,
            api_key=api_key,
            request_id=request_id,
            domain=args.domain,
            session_id=args.session_id,
            message=args.message,
        ),
    ]

    chat_result = results[-1]
    if args.feedback and chat_result.ok:
        results.append(
            smoke_feedback(
                base_url=base_url,
                api_key=api_key,
                request_id=request_id,
                session_id=args.session_id,
                chat_summary=chat_result.summary,
            )
        )

    report = build_report(base_url=base_url, request_id=request_id, results=results)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as report_file:
            report_file.write(report)
            report_file.write("\n")
    print(report)

    return 0 if all(result.ok for result in results) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run sanitized HTTP smoke checks against supportFAQagent staging."
    )
    parser.add_argument("--base-url", required=True, help="Base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--api-key", help="Private API key. Prefer API_SECRET_KEY env var.")
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--request-id", help="Stable X-Request-ID for correlation.")
    parser.add_argument("--feedback", action="store_true", help="Also smoke POST /feedback.")
    parser.add_argument("--output", help="Write sanitized Markdown report to this path.")
    return parser.parse_args()


def smoke_health(base_url: str) -> SmokeResult:
    started_at = time.perf_counter()
    status, payload, error = request_json("GET", f"{base_url}/health")
    latency_ms = elapsed_ms(started_at)
    ok = status == 200 and payload.get("status") == "ok"
    return SmokeResult(
        name="health",
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        summary={"status_value": payload.get("status")},
        error=error,
    )


def smoke_domains(
    base_url: str,
    api_key: str,
    request_id: str,
    expected_domain: str,
) -> SmokeResult:
    started_at = time.perf_counter()
    status, payload, error = request_json(
        "GET",
        f"{base_url}/domains",
        headers=auth_headers(api_key, request_id),
    )
    latency_ms = elapsed_ms(started_at)
    domains = payload.get("domains") if isinstance(payload.get("domains"), list) else []
    ok = status == 200 and expected_domain in domains
    return SmokeResult(
        name="domains",
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        summary={
            "domain_count": len(domains),
            "expected_domain_present": expected_domain in domains,
        },
        error=error,
    )


def smoke_chat(
    base_url: str,
    api_key: str,
    request_id: str,
    domain: str,
    session_id: str,
    message: str,
) -> SmokeResult:
    started_at = time.perf_counter()
    status, payload, error = request_json(
        "POST",
        f"{base_url}/chat",
        headers=auth_headers(api_key, request_id),
        body={"domain": domain, "session_id": session_id, "message": message},
    )
    latency_ms = elapsed_ms(started_at)
    references = payload.get("references") if isinstance(payload.get("references"), list) else []
    handoff_reasons = (
        payload.get("handoff_reasons")
        if isinstance(payload.get("handoff_reasons"), list)
        else []
    )
    ok = (
        status == 200
        and payload.get("request_id") == request_id
        and payload.get("domain") == domain
        and isinstance(payload.get("confidence"), (int, float))
        and isinstance(payload.get("escalated"), bool)
        and isinstance(references, list)
        and isinstance(handoff_reasons, list)
    )
    return SmokeResult(
        name="chat",
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        summary={
            "request_id": payload.get("request_id"),
            "domain": payload.get("domain"),
            "confidence": payload.get("confidence"),
            "escalated": payload.get("escalated"),
            "handoff_reasons": handoff_reasons,
            "references_count": len(references),
            "error_code": payload.get("error_code"),
        },
        error=error,
    )


def smoke_feedback(
    base_url: str,
    api_key: str,
    request_id: str,
    session_id: str,
    chat_summary: dict[str, Any],
) -> SmokeResult:
    started_at = time.perf_counter()
    status, payload, error = request_json(
        "POST",
        f"{base_url}/feedback",
        headers=auth_headers(api_key, request_id),
        body={
            "request_id": request_id,
            "session_id": session_id,
            "helpful": True,
            "source": "staging_smoke",
            "escalated": chat_summary.get("escalated"),
            "handoff_reasons": chat_summary.get("handoff_reasons") or [],
            "references": [],
            "error_code": chat_summary.get("error_code"),
        },
    )
    latency_ms = elapsed_ms(started_at)
    ok = status == 200 and payload.get("accepted") is True
    return SmokeResult(
        name="feedback",
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        summary={
            "accepted": payload.get("accepted"),
            "status": payload.get("status"),
            "storage": payload.get("storage"),
        },
        error=error,
    )


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int | None, dict[str, Any], str | None]:
    data = None
    request_headers = headers or {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **request_headers}

    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
            return response.status, parse_json(payload), None
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        return exc.code, parse_json(payload), f"http_error:{exc.code}"
    except URLError as exc:
        return None, {}, f"url_error:{exc.reason}"
    except TimeoutError:
        return None, {}, "timeout"


def auth_headers(api_key: str, request_id: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "X-Request-ID": request_id,
    }


def parse_json(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_report(base_url: str, request_id: str, results: list[SmokeResult]) -> str:
    lines = [
        "# Staging HTTP Smoke Report",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- base_url: {base_url}",
        f"- request_id: {request_id}",
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
            "- API keys, headers, raw payloads, raw session identifiers, prompts and full answers are not printed.",
            "- Use backend logs with the same request_id to inspect retrieval_backend, total_ms, retrieval_ms and llm_ms.",
        ]
    )
    return "\n".join(lines)


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
