from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from typing import Mapping
from uuid import uuid4


SEND_TEXT_PREFIX = "/message/sendText/"


def validate_send_text_request(
    *,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
    expected_api_key: str,
) -> tuple[int, dict[str, str]]:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    if not expected_api_key or normalized_headers.get("apikey") != expected_api_key:
        return 401, {"status": "invalid_api_key"}
    if not path.startswith(SEND_TEXT_PREFIX) or not path.removeprefix(SEND_TEXT_PREFIX):
        return 404, {"status": "unknown_endpoint"}
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"status": "invalid_json"}
    if not isinstance(payload, dict):
        return 422, {"status": "invalid_payload"}
    number = payload.get("number")
    text = payload.get("text")
    if not isinstance(number, str) or not number.strip() or len(number) > 200:
        return 422, {"status": "invalid_number"}
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        return 422, {"status": "invalid_text"}
    return 200, {"status": "accepted", "message_id": str(uuid4())}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        status, response = validate_send_text_request(
            path=self.path,
            headers=self.headers,
            body=body,
            expected_api_key=os.getenv("EVOLUTION_API_KEY", ""),
        )
        forced_status = os.getenv("EVOLUTION_MOCK_FORCE_STATUS")
        if forced_status:
            status = int(forced_status)
            response = {"status": "forced_failure"}
        encoded = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Evolution sendText contract mock.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if not os.getenv("EVOLUTION_API_KEY"):
        parser.error("EVOLUTION_API_KEY is required")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
