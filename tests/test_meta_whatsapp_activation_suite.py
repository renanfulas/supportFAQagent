from __future__ import annotations

from argparse import Namespace
import subprocess
import sys

from scripts import meta_whatsapp_activation_suite as suite
from scripts import meta_whatsapp_private_smoke as smoke


def base_args(tmp_path, **overrides):
    values = {
        "output_dir": str(tmp_path),
        "base_url": "http://127.0.0.1:8000",
        "environment": "private-lab",
        "operator": "Renan",
        "decision": "pending",
        "meta_webhook": False,
        "meta_chat_inbound": False,
        "meta_chat_from": None,
        "meta_chat_text": "safe inbound",
        "meta_outbox_message": False,
        "meta_outbox_to": None,
        "meta_outbox_text": "safe outbound",
        "meta_otp": False,
        "meta_otp_phone": None,
        "meta_otp_code": "000000",
        "meta_otp_expires_seconds": 300,
        "hermes_otp": False,
        "hermes_phone": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_suite_writes_preflight_and_evidence_without_smoke_by_default(tmp_path) -> None:
    result = suite.run_suite(base_args(tmp_path))

    assert result.preflight_report.exists()
    assert result.smoke_report is None
    assert result.evidence_report.exists()
    assert result.evidence_ready is False
    evidence_report = result.evidence_report.read_text(encoding="utf-8")
    assert "ready_for_promotion: false" in evidence_report
    assert "+15551234567" not in evidence_report


def test_direct_suite_invocation_bootstraps_repo_imports(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/meta_whatsapp_activation_suite.py",
            "--output-dir",
            str(tmp_path),
            "--decision",
            "pending",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Meta/Hermes activation suite completed" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr


def test_suite_runs_selected_meta_webhook_smoke(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setenv("META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-token")

    monkeypatch.setattr(
        smoke,
        "smoke_meta_webhook_verification",
        lambda **kwargs: smoke.CheckResult(
            name="meta_webhook_verification",
            ok=True,
            status=200,
            latency_ms=1.0,
            summary={"challenge_echoed": True},
        ),
    )
    monkeypatch.setattr(
        smoke,
        "smoke_meta_signed_status_webhook",
        lambda **kwargs: smoke.CheckResult(
            name="meta_signed_status_webhook",
            ok=True,
            status=200,
            latency_ms=1.0,
            summary={"accepted": True},
        ),
    )

    result = suite.run_suite(base_args(tmp_path, meta_webhook=True))

    assert result.smoke_report is not None
    smoke_report = result.smoke_report.read_text(encoding="utf-8")
    assert "meta_webhook_verification" in smoke_report
    assert "meta_signed_status_webhook" in smoke_report
    assert "app-secret" not in smoke_report
    assert "verify-token" not in smoke_report


def test_suite_requires_recipient_before_env_for_real_send_flags(tmp_path) -> None:
    try:
        suite.run_suite(base_args(tmp_path, meta_outbox_message=True))
    except ValueError as exc:
        assert "--meta-outbox-to is required" in str(exc)
    else:
        raise AssertionError("expected missing recipient")


def test_suite_requires_env_after_recipient_for_real_send_flags(tmp_path) -> None:
    try:
        suite.run_suite(
            base_args(
                tmp_path,
                meta_outbox_message=True,
                meta_outbox_to="+15551234567",
            )
        )
    except ValueError as exc:
        assert "Missing required env" in str(exc)
    else:
        raise AssertionError("expected missing env")


def test_suite_rejects_meta_outbox_without_recipient(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT", "meta_whatsapp")

    try:
        suite.run_suite(base_args(tmp_path, meta_outbox_message=True))
    except ValueError as exc:
        assert "--meta-outbox-to is required" in str(exc)
    else:
        raise AssertionError("expected missing recipient")


def test_summary_is_sanitized(tmp_path) -> None:
    result = suite.SuiteResult(
        output_dir=tmp_path,
        preflight_report=tmp_path / "preflight.json",
        smoke_report=None,
        evidence_report=tmp_path / "evidence.md",
        evidence_ready=False,
        smoke_passed=True,
    )

    summary = suite.render_summary(result)

    assert "values: sanitized" in summary
    assert "not_run" in summary


def test_summary_redacts_secret_like_paths(tmp_path) -> None:
    unsafe_output_dir = tmp_path / "token=provider-private-marker-+15551234567"
    result = suite.SuiteResult(
        output_dir=unsafe_output_dir,
        preflight_report=unsafe_output_dir / "meta-whatsapp-preflight.json",
        smoke_report=unsafe_output_dir / "meta-whatsapp-smoke.md",
        evidence_report=unsafe_output_dir / "meta-whatsapp-activation-evidence.md",
        evidence_ready=False,
        smoke_passed=True,
    )

    summary = suite.render_summary(result)

    assert "redacted-path" in summary
    assert "provider-private-marker" not in summary
    assert "+15551234567" not in summary


def test_suite_rejects_hermes_without_recipient(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HERMES_BASE_URL", "https://hermes.example.test")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", "hermes-secret")
    output_dir = tmp_path / "activation-output"

    try:
        suite.run_suite(base_args(output_dir, hermes_otp=True))
    except ValueError as exc:
        assert "--hermes-phone is required" in str(exc)
    else:
        raise AssertionError("expected missing Hermes recipient")
    assert not output_dir.exists()
