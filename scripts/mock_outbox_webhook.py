from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os


MAX_SKEW_SECONDS = 300
SEEN_KEYS: set[str] = set()


def verify_signature(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
    now: int | None = None,
) -> bool:
    if not secret or not timestamp or not signature or not signature.startswith("sha256="):
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else int(datetime.now(UTC).timestamp())
    if abs(current - sent_at) > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        secret = os.getenv("OUTBOX_WEBHOOK_SECRET", "")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        valid = verify_signature(
            body=body,
            timestamp=self.headers.get("X-Webhook-Timestamp"),
            signature=self.headers.get("X-Webhook-Signature"),
            secret=secret,
        )
        if not valid:
            self._respond(401, b'{"status":"invalid_signature"}')
            return
        key = self.headers.get("X-Idempotency-Key", "")
        if not key:
            self._respond(400, b'{"status":"missing_idempotency_key"}')
            return
        duplicate = key in SEEN_KEYS
        SEEN_KEYS.add(key)
        self._respond(200, b'{"status":"duplicate"}' if duplicate else b'{"status":"accepted"}')

    def log_message(self, *_: object) -> None:
        return

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local signed outbox webhook simulator.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not os.getenv("OUTBOX_WEBHOOK_SECRET"):
        parser.error("OUTBOX_WEBHOOK_SECRET is required")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
