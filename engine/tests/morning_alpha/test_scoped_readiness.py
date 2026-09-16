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
