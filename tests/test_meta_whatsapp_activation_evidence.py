from __future__ import annotations

import json
import subprocess
import sys

from scripts import meta_whatsapp_activation_evidence as evidence


def test_parse_preflight_report_extracts_only_readiness(tmp_path) -> None:
    report_path = tmp_path / "preflight.json"
    report_path.write_text(
        json.dumps(
            {
                "ready": True,
                "modes": [
                    {
                        "mode": "meta-webhook",
                        "ready": True,
                        "present": ["META_WHATSAPP_APP_SECRET"],
                        "missing": [],
                        "invalid": [],
                        "recommended_missing": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    ready, modes = evidence.parse_preflight_report(report_path)

    assert ready is True
    assert modes[0].mode == "meta-webhook"
    assert modes[0].ready is True


def test_parse_smoke_report_extracts_check_status_without_summary(tmp_path) -> None:
    report_path = tmp_path / "smoke.md"
    report_path.write_text(
        "\n".join(
            [
                "# Meta/Hermes Private Smoke Report",
                "### meta_signed_status_webhook",
                "- ok: true",
                "- status: 200",
                "- error: none",
                "- summary:",
                "  - accepted: true",
            ]
        ),
        encoding="utf-8",
    )

    checks = evidence.parse_smoke_report(report_path)

    assert checks == (
        evidence.SmokeCheck(
            name="meta_signed_status_webhook",
            ok=True,
            status="200",
            error="none",
        ),
    )


def test_render_evidence_is_sanitized_and_requires_promote_decision(tmp_path) -> None:
    preflight_path = tmp_path / "preflight.json"
    smoke_path = tmp_path / "smoke.md"
    preflight_path.write_text(
        json.dumps(
            {
                "ready": True,
                "modes": [
                    {
                        "mode": "hermes-otp",
                        "ready": True,
                        "missing": [],
                        "invalid": [],
                        "recommended_missing": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    smoke_path.write_text(
        "\n".join(
            [
                "### hermes_otp_delivery",
                "- ok: true",
                "- status: 202",
                "- error: none",
                "raw secret should not be copied: token=provider-private-marker",
            ]
        ),
        encoding="utf-8",
    )

    result = evidence.build_evidence(
        environment="staging token=provider-private-marker",
        operator="Renan",
        decision="pending",
        preflight_report=preflight_path,
        smoke_reports=(smoke_path,),
    )
    report = evidence.render_evidence(result)

    assert evidence.evidence_is_ready(result) is False
    assert "ready_for_promotion: false" in report
    assert "environment: redacted" in report
    assert "provider-private-marker" not in report
    assert "raw secret" not in report


def test_evidence_is_ready_only_with_promote_and_all_checks_ok() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=("meta-webhook",),
        required_checks=("meta_webhook_verification",),
        preflight_ready=True,
        preflight_modes=(
            evidence.PreflightMode(
                mode="meta-webhook",
                ready=True,
                missing=(),
                invalid=(),
                recommended_missing=(),
            ),
        ),
        smoke_checks=(
            evidence.SmokeCheck(
                name="meta_webhook_verification",
                ok=True,
                status="200",
                error="none",
            ),
        ),
    )

    assert evidence.evidence_is_ready(result) is True


def test_evidence_requires_default_meta_promotion_checks() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=(),
        required_checks=evidence.DEFAULT_REQUIRED_CHECKS,
        preflight_ready=True,
        preflight_modes=(),
        smoke_checks=(
            evidence.SmokeCheck(
                name="meta_webhook_verification",
                ok=True,
                status="200",
                error="none",
            ),
        ),
    )
    report = evidence.render_evidence(result)

    assert evidence.evidence_is_ready(result) is False
    assert "ready_for_promotion: false" in report
    assert "missing_required_checks: meta_signed_status_webhook" in report
    assert "meta_chat_inbound_message" in report
    assert "meta_outbox_message_delivery" in report
    assert "meta_otp_delivery" in report


def test_evidence_reports_failed_required_checks() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=(),
        required_checks=("meta_otp_delivery",),
        preflight_ready=True,
        preflight_modes=(),
        smoke_checks=(
            evidence.SmokeCheck(
                name="meta_otp_delivery",
                ok=False,
                status="none",
                error="RuntimeError",
            ),
        ),
    )
    gate = evidence.promotion_gate_status(result)

    assert evidence.evidence_is_ready(result) is False
    assert gate["missing_required_checks"] == ()
    assert gate["failed_required_checks"] == ("meta_otp_delivery",)


def test_evidence_requires_default_meta_preflight_modes() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=evidence.DEFAULT_REQUIRED_MODES,
        required_checks=(),
        preflight_ready=True,
        preflight_modes=(
            evidence.PreflightMode(
                mode="meta-webhook",
                ready=True,
                missing=(),
                invalid=(),
                recommended_missing=(),
            ),
        ),
        smoke_checks=(
            evidence.SmokeCheck(
                name="diagnostic",
                ok=True,
                status="200",
                error="none",
            ),
        ),
    )
    report = evidence.render_evidence(result)

    assert evidence.evidence_is_ready(result) is False
    assert "missing_required_modes: meta-chat" in report
    assert "meta-outbox-message" in report
    assert "meta-otp" in report


def test_evidence_ignores_non_required_failed_preflight_modes() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=("meta-webhook",),
        required_checks=("meta_webhook_verification",),
        preflight_ready=False,
        preflight_modes=(
            evidence.PreflightMode(
                mode="meta-webhook",
                ready=True,
                missing=(),
                invalid=(),
                recommended_missing=(),
            ),
            evidence.PreflightMode(
                mode="hermes-otp",
                ready=False,
                missing=("HERMES_BASE_URL",),
                invalid=(),
                recommended_missing=(),
            ),
        ),
        smoke_checks=(
            evidence.SmokeCheck(
                name="meta_webhook_verification",
                ok=True,
                status="200",
                error="none",
            ),
        ),
    )

    assert evidence.evidence_is_ready(result) is True


def test_evidence_reports_failed_required_preflight_modes() -> None:
    result = evidence.ActivationEvidence(
        environment="private-lab",
        operator="Renan",
        decision="promote",
        required_modes=("meta-otp",),
        required_checks=(),
        preflight_ready=False,
        preflight_modes=(
            evidence.PreflightMode(
                mode="meta-otp",
                ready=False,
                missing=("META_WHATSAPP_OTP_TEMPLATE_NAME",),
                invalid=(),
                recommended_missing=(),
            ),
        ),
        smoke_checks=(
            evidence.SmokeCheck(
                name="diagnostic",
                ok=True,
                status="200",
                error="none",
            ),
        ),
    )
    gate = evidence.promotion_gate_status(result)

    assert evidence.evidence_is_ready(result) is False
    assert gate["missing_required_modes"] == ()
    assert gate["failed_required_modes"] == ("meta-otp",)


def test_main_returns_non_zero_without_smoke_report(monkeypatch, tmp_path, capsys) -> None:
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps({"ready": True, "modes": []}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "meta_whatsapp_activation_evidence.py",
            "--decision",
            "promote",
            "--preflight-report",
            str(preflight_path),
        ],
    )

    code = evidence.main()
    output = capsys.readouterr()

    assert code == 1
    assert "report: missing" in output.out


def test_main_reports_missing_preflight_without_traceback(monkeypatch, tmp_path, capsys) -> None:
    missing_path = tmp_path / "missing-preflight.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "meta_whatsapp_activation_evidence.py",
            "--preflight-report",
            str(missing_path),
        ],
    )

    code = evidence.main()
    output = capsys.readouterr()

    assert code == 2
    assert "Preflight report not found" in output.err
    assert "Traceback" not in output.err


def test_main_reports_invalid_preflight_json_without_traceback(monkeypatch, tmp_path, capsys) -> None:
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "meta_whatsapp_activation_evidence.py",
            "--preflight-report",
            str(preflight_path),
        ],
    )

    code = evidence.main()
    output = capsys.readouterr()

    assert code == 2
    assert "Preflight report is not valid JSON" in output.err
    assert "Traceback" not in output.err


def test_direct_evidence_invocation_reports_missing_file_without_traceback(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/meta_whatsapp_activation_evidence.py",
            "--preflight-report",
            str(tmp_path / "missing-preflight.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Preflight report not found" in result.stderr
    assert "Traceback" not in result.stderr
