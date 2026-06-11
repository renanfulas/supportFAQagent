import pytest

from scripts.phase0_operational_report import REQUIRED_GATES, render_report


def test_phase0_report_requires_every_gate_to_pass() -> None:
    statuses = {gate: "passed" for gate in REQUIRED_GATES}
    statuses["restore"] = "blocked"

    report = render_report(statuses)

    assert "decision: not_approved" in report
    assert "restore: blocked" in report


def test_phase0_report_approves_complete_evidence() -> None:
    report = render_report({gate: "passed" for gate in REQUIRED_GATES})

    assert "decision: approved" in report


def test_phase0_report_rejects_unknown_gate() -> None:
    with pytest.raises(ValueError):
        render_report({"unknown": "passed"})
