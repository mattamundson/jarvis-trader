import json

from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.scoped_readiness import (
    RELATIVE_STRENGTH_BREAKOUT_SCOPE,
    scope_readiness_report,
)


def _report(*reasons: str) -> DataReadinessReport:
    return DataReadinessReport(
        ready=not reasons,
        root="fixture",
        file_count=1,
        symbols=("SPY",),
        reasons=reasons,
    )


def test_rsb_scope_allows_only_missing_earnings_evidence():
    report = scope_readiness_report(
        _report("EARNINGS_EVENTS_MISSING", "ARTIFACT_KIND_MISSING:earnings_events"),
        RELATIVE_STRENGTH_BREAKOUT_SCOPE,
    )

    assert report.ready is True
    assert report.reasons == ()


def test_rsb_scope_preserves_unrelated_blockers():
    report = scope_readiness_report(
        _report("EARNINGS_EVENTS_MISSING", "SECTOR_HISTORY_MISSING"),
        RELATIVE_STRENGTH_BREAKOUT_SCOPE,
    )

    assert report.ready is False
    assert report.reasons == ("SECTOR_HISTORY_MISSING",)


def test_rsb_scope_does_not_waive_corrupt_optional_artifact_evidence():
    report = scope_readiness_report(
        _report(
            "EARNINGS_EVENTS_MISSING",
            "ARTIFACT_HASH_MISMATCH:evidence/earnings.parquet",
        ),
        RELATIVE_STRENGTH_BREAKOUT_SCOPE,
    )

    assert report.ready is False
    assert report.reasons == ("ARTIFACT_HASH_MISMATCH:evidence/earnings.parquet",)


def test_unknown_strategy_scope_fails_closed():
    report = scope_readiness_report(_report(), "unknown@1.0.0")

    assert report.ready is False
    assert report.reasons == ("UNSUPPORTED_STRATEGY_SCOPE:unknown@1.0.0",)


def test_inconsistent_base_report_stays_blocked():
    report = DataReadinessReport(
        ready=False,
        root="fixture",
        file_count=1,
        symbols=("SPY",),
        reasons=(),
    )

    scoped = scope_readiness_report(report, RELATIVE_STRENGTH_BREAKOUT_SCOPE)

    assert scoped.ready is False
    assert scoped.reasons == ("UNEXPLAINED_READINESS_FAILURE",)


def test_relative_strength_cli_applies_scoped_readiness(monkeypatch, capsys, tmp_path):
    from morning_alpha import cli

    monkeypatch.setattr(
        cli,
        "inspect_research_files",
        lambda _root: _report(
            "EARNINGS_EVENTS_MISSING",
            "ARTIFACT_KIND_MISSING:earnings_events",
        ),
    )
    monkeypatch.setattr(cli, "render_edge_research_report", lambda _report: "RSB_READY\n")

    class _Status:
        value = "evidence_ready"

    class _Result:
        status = _Status()

    rc = cli.main(
        ["research-relative-strength", "--data-root", str(tmp_path)],
        relative_strength_handler=lambda _root: _Result(),
    )

    assert rc == 0
    assert capsys.readouterr().out == "RSB_READY\n"


def test_data_check_cli_can_report_rsb_scoped_readiness(monkeypatch, capsys, tmp_path):
    from morning_alpha import cli

    monkeypatch.setattr(
        cli,
        "inspect_research_files",
        lambda _root: _report(
            "EARNINGS_EVENTS_MISSING",
            "ARTIFACT_KIND_MISSING:earnings_events",
        ),
    )

    rc = cli.main(
        [
            "research-data-check",
            "--data-root",
            str(tmp_path),
            "--strategy",
            RELATIVE_STRENGTH_BREAKOUT_SCOPE,
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ready"] is True
    assert payload["reasons"] == []
