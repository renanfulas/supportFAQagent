import pytest

from scripts.phase0_restore_validate import (
    SUBCHECKS,
    evaluate_restore,
    parse_timestamp,
    render_restore_report,
)


def _all(status: str) -> dict[str, str]:
    return {name: status for name in SUBCHECKS}


def _drill(**overrides):
    base = dict(
        snapshot_timestamp=parse_timestamp("2026-07-01T00:00:00Z"),
        restore_started_at=parse_timestamp("2026-07-01T02:00:00Z"),
        restore_finished_at=parse_timestamp("2026-07-01T03:10:00Z"),
        latest_data_timestamp=parse_timestamp("2026-06-30T23:50:00Z"),
        subchecks=_all("passed"),
    )
    base.update(overrides)
    return evaluate_restore(**base)


def test_parse_timestamp_handles_zulu_and_missing() -> None:
    assert parse_timestamp("2026-07-01T00:00:00Z") is not None
    assert parse_timestamp(None) is None
    assert parse_timestamp("not-a-date") is None


def test_healthy_drill_passes_within_thresholds() -> None:
    evaluation = _drill()

    assert evaluation.verdict == "passed"
    assert evaluation.rto_ok and evaluation.rpo_ok
    assert round(evaluation.rto_hours, 2) == 1.17
    assert round(evaluation.rpo_hours, 2) == 0.17


def test_rto_over_target_fails() -> None:
    evaluation = _drill(restore_finished_at=parse_timestamp("2026-07-01T07:00:00Z"))

    assert evaluation.verdict == "failed"
    assert not evaluation.rto_ok


def test_rpo_over_target_fails() -> None:
    evaluation = _drill(latest_data_timestamp=parse_timestamp("2026-06-29T00:00:00Z"))

    assert evaluation.verdict == "failed"
    assert not evaluation.rpo_ok


def test_failed_subcheck_fails() -> None:
    subchecks = _all("passed")
    subchecks["readiness"] = "failed"

    assert _drill(subchecks=subchecks).verdict == "failed"


def test_pending_subcheck_blocks() -> None:
    subchecks = _all("passed")
    subchecks["smoke"] = "pending"

    assert _drill(subchecks=subchecks).verdict == "blocked"


def test_incomplete_timing_blocks() -> None:
    assert _drill(restore_finished_at=None).verdict == "blocked"


def test_unknown_subcheck_rejected() -> None:
    with pytest.raises(ValueError):
        _drill(subchecks={"unknown": "passed"})


def test_report_is_sanitized_and_shows_verdict() -> None:
    report = render_restore_report(_drill())

    assert "restore verdict: passed" in report
    assert "## Sanitization" in report
    assert "--restore passed" in report
    # Only timestamps/status/metrics; nothing that looks like a host or secret.
    for leaked in ("http://", "https://", "@", "password", "token"):
        assert leaked not in report
