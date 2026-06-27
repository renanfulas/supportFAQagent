"""Append-only insurance sink for persisted conversation turns.

This is the off-box durability seam from the converged persistence design:
Postgres is the source of truth on the hot path, and every persisted turn is
fanned out (via the transactional outbox) to an isolated append-only sink so a
VPS restart, deploy, or crash cannot lose acknowledged turns.

The sink is intentionally a thin, swappable adapter. The default transport
writes append-only NDJSON to a local path, which is enough to validate the
contract end to end. Replacing it with a managed log, queue, or object store
(Alexandre/Silotto) means adding a sink class here and a branch in
``build_archive_sink_from_env`` — no caller or schema change.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


SUPPORTED_SINK_TRANSPORTS = {"append_only_file", "s3"}


@runtime_checkable
class ConversationArchiveSink(Protocol):
    """Durable, append-only destination for archived conversation turns."""

    def append(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        ...


class AppendOnlyFileSink:
    """Append-only NDJSON sink, off the hot path.

    Each record is written as a single JSON line, flushed and ``fsync``-ed
    before the call returns, so an acknowledged turn survives a process crash.
    The writer only ever appends; it never rewrites or truncates the file.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        line = _archive_record(
            idempotency_key=idempotency_key,
            event_type=event_type,
            request_id=request_id,
            payload=payload,
        ).decode("utf-8")
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())


def _archive_record(
    *,
    idempotency_key: str,
    event_type: str,
    request_id: str | None,
    payload: dict[str, Any],
) -> bytes:
    record = {
        "idempotency_key": idempotency_key,
        "event_type": event_type,
        "request_id": request_id,
        "payload": payload,
    }
    line = json.dumps(
        record,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return line.encode("utf-8")


def _turn_ref(idempotency_key: str) -> str:
    ref = idempotency_key.split(":", 1)[-1].strip()
    return ref or idempotency_key.strip() or "unknown"


class S3ObjectSink:
    """Append-only sink backed by S3-compatible object storage.

    Object stores have no append, so every turn becomes one immutable object at
    a deterministic key (``<prefix>/<shard>/<turn_ref>.json``). The key is a pure
    function of the turn, so an outbox re-delivery overwrites the same object
    with identical bytes — idempotent without server-side conditionals, which
    keeps the adapter portable across AWS S3, Cloudflare R2, Backblaze B2 and
    MinIO (selected via ``endpoint_url``). Credentials come from the standard
    boto3 chain (env / instance role); this module never reads secrets directly.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "conversations",
        client: Any | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        if client is not None:
            self._client = client
        else:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - exercised via env
                raise RuntimeError(
                    "the s3 conversation archive sink requires the 's3' extra "
                    "(pip install '.[s3]')"
                ) from exc
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
            )

    def _key(self, turn_ref: str) -> str:
        shard = turn_ref[:2] if len(turn_ref) >= 2 else "00"
        suffix = f"{turn_ref}.json"
        return f"{self._prefix}/{shard}/{suffix}" if self._prefix else f"{shard}/{suffix}"

    def append(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        body = _archive_record(
            idempotency_key=idempotency_key,
            event_type=event_type,
            request_id=request_id,
            payload=payload,
        )
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(_turn_ref(idempotency_key)),
            Body=body,
            ContentType="application/json",
        )


def resolve_sink_transport() -> str:
    transport = (
        os.getenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "append_only_file")
        .strip()
        .lower()
    ) or "append_only_file"
    if transport not in SUPPORTED_SINK_TRANSPORTS:
        raise ValueError(
            f"unsupported conversation archive sink transport: {transport}"
        )
    return transport


def build_archive_sink_from_env() -> ConversationArchiveSink:
    """Build the configured sink from environment variables.

    Reads environment directly (like the rest of the outbox dispatcher) so the
    standalone worker stays decoupled from the application Settings object.
    """

    transport = resolve_sink_transport()
    if transport == "append_only_file":
        path = os.getenv("CONVERSATION_ARCHIVE_SINK_PATH")
        if not path or not path.strip():
            raise RuntimeError("CONVERSATION_ARCHIVE_SINK_PATH is not configured")
        return AppendOnlyFileSink(path.strip())
    if transport == "s3":
        bucket = os.getenv("CONVERSATION_ARCHIVE_SINK_BUCKET")
        if not bucket or not bucket.strip():
            raise RuntimeError("CONVERSATION_ARCHIVE_SINK_BUCKET is not configured")
        prefix = (os.getenv("CONVERSATION_ARCHIVE_SINK_PREFIX") or "conversations").strip()
        endpoint_url = (os.getenv("CONVERSATION_ARCHIVE_SINK_ENDPOINT_URL") or "").strip()
        region = (os.getenv("CONVERSATION_ARCHIVE_SINK_REGION") or "").strip()
        return S3ObjectSink(
            bucket=bucket.strip(),
            prefix=prefix or "conversations",
            endpoint_url=endpoint_url or None,
            region=region or None,
        )
    raise ValueError(f"unsupported conversation archive sink transport: {transport}")
