from scripts.mock_outbox_webhook import verify_signature


def test_signature_verifier_rejects_replay_window_and_invalid_signature() -> None:
    body = b'{"request_id":"req-1"}'
    secret = "dedicated-secret"
    timestamp = "1000"
    import hashlib
    import hmac

    signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    assert verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret=secret,
        now=1001,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret=secret,
        now=1400,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature="sha256=invalid",
        secret=secret,
        now=1001,
    )
    assert not verify_signature(
        body=body,
        timestamp=timestamp,
        signature=f"sha256={signature}",
        secret="",
        now=1001,
    )
