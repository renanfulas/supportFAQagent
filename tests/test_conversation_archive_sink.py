import json
from pathlib import Path

import pytest

from app.conversations.archive_sink import (
    AppendOnlyFileSink,
    S3ObjectSink,
    build_archive_sink_from_env,
    resolve_sink_transport,
)
from scripts.dispatch_outbox import (
    deliver,
    resolve_delivery_route,
    resolve_delivery_transport,
)


def _read_lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_append_only_file_sink_writes_one_json_line_per_turn(tmp_path: Path) -> None:
    sink_path = tmp_path / "nested" / "archive.ndjson"
    sink = AppendOnlyFileSink(sink_path)

    sink.append(
        idempotency_key="archive:turn-1",
        event_type="conversation.turn.archived",
        request_id="req-1",
        payload={"turn_id": "turn-1", "summary": "safe"},
    )
    sink.append(
        idempotency_key="archive:turn-2",
        event_type="conversation.turn.archived",
        request_id="req-2",
        payload={"turn_id": "turn-2", "summary": "safe"},
    )

    records = _read_lines(sink_path)
    assert [record["idempotency_key"] for record in records] == [
        "archive:turn-1",
        "archive:turn-2",
    ]
    assert records[0]["payload"]["turn_id"] == "turn-1"
    assert records[0]["event_type"] == "conversation.turn.archived"


def test_append_only_file_sink_never_truncates(tmp_path: Path) -> None:
    sink_path = tmp_path / "archive.ndjson"
    sink_path.write_text('{"idempotency_key":"archive:pre"}\n', encoding="utf-8")

    AppendOnlyFileSink(sink_path).append(
        idempotency_key="archive:new",
        event_type="conversation.turn.archived",
        request_id="req-new",
        payload={"turn_id": "new"},
    )

    records = _read_lines(sink_path)
    assert [record["idempotency_key"] for record in records] == [
        "archive:pre",
        "archive:new",
    ]


def test_build_sink_defaults_to_append_only_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", raising=False)
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_PATH", str(tmp_path / "a.ndjson"))

    assert resolve_sink_transport() == "append_only_file"
    assert isinstance(build_archive_sink_from_env(), AppendOnlyFileSink)


def test_build_sink_requires_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "append_only_file")
    monkeypatch.delenv("CONVERSATION_ARCHIVE_SINK_PATH", raising=False)

    with pytest.raises(RuntimeError, match="CONVERSATION_ARCHIVE_SINK_PATH"):
        build_archive_sink_from_env()


def test_build_sink_rejects_unsupported_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "carrier_pigeon")

    with pytest.raises(ValueError, match="unsupported conversation archive sink"):
        build_archive_sink_from_env()


def test_archive_event_resolves_to_sink_route_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT", raising=False)
    route = resolve_delivery_route("conversation.turn.archived")

    assert route.name == "conversation_archive"
    assert route.default_transport == "append_only_sink"
    assert resolve_delivery_transport(route) == "append_only_sink"


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, str]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        self.calls.append((Bucket, Key, ContentType))
        self.objects[Key] = Body


def test_s3_sink_writes_deterministic_idempotent_object() -> None:
    client = _FakeS3Client()
    sink = S3ObjectSink(bucket="archive-bucket", prefix="conversations", client=client)

    for _ in range(2):  # re-delivery must land on the same immutable key
        sink.append(
            idempotency_key="archive:ab12cd34",
            event_type="conversation.turn.archived",
            request_id="req-1",
            payload={"turn_id": "ab12cd34", "session_hash": "safe-hash"},
        )

    assert list(client.objects.keys()) == ["conversations/ab/ab12cd34.json"]
    assert len(client.calls) == 2
    assert client.calls[0] == (
        "archive-bucket",
        "conversations/ab/ab12cd34.json",
        "application/json",
    )
    body = json.loads(client.objects["conversations/ab/ab12cd34.json"])
    assert body["payload"]["turn_id"] == "ab12cd34"
    assert body["event_type"] == "conversation.turn.archived"


def test_s3_sink_honours_empty_prefix() -> None:
    client = _FakeS3Client()
    sink = S3ObjectSink(bucket="b", prefix="", client=client)

    sink.append(
        idempotency_key="archive:ff99",
        event_type="conversation.turn.archived",
        request_id=None,
        payload={"turn_id": "ff99"},
    )

    assert list(client.objects.keys()) == ["ff/ff99.json"]


def test_s3_factory_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "s3")
    monkeypatch.delenv("CONVERSATION_ARCHIVE_SINK_BUCKET", raising=False)

    assert resolve_sink_transport() == "s3"
    with pytest.raises(RuntimeError, match="CONVERSATION_ARCHIVE_SINK_BUCKET"):
        build_archive_sink_from_env()


def test_deliver_archives_turn_to_append_only_sink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sink_path = tmp_path / "archive.ndjson"
    monkeypatch.delenv("OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT", raising=False)
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_TRANSPORT", "append_only_file")
    monkeypatch.setenv("CONVERSATION_ARCHIVE_SINK_PATH", str(sink_path))

    deliver(
        {
            "event_type": "conversation.turn.archived",
            "request_id": "req-archive",
            "idempotency_key": "archive:turn-9",
            "payload_sanitized": {"turn_id": "turn-9", "summary": "safe"},
        }
    )

    records = _read_lines(sink_path)
    assert len(records) == 1
    assert records[0]["request_id"] == "req-archive"
    assert records[0]["payload"]["turn_id"] == "turn-9"
