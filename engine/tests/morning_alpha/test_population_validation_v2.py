from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from morning_alpha.models import StrategyKey
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.candidate_store import CandidatePopulationWriter
from morning_alpha.research.population import (
    CandidateDecisionState,
    CandidateObservation,
    HistoricalUniverseMember,
    PopulationBuildResult,
    PopulationDecisionClock,
    candidate_identity,
)
from morning_alpha.research.splits import SplitKind, SplitRegistry, TemporalSplit
from morning_alpha.research.validation import PopulationValidator, ValidationCode

NY = ZoneInfo("America/New_York")
STRATEGY = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")


def _obs(ts: datetime, **overrides):
    data = dict(
        candidate_id=candidate_identity(STRATEGY, "SEC-1", ts),
        campaign_id="morning_alpha_v1",
        strategy=STRATEGY,
        stable_security_id="SEC-1",
        symbol="AAA",
        decision_timestamp=ts,
        trading_date=ts.date(),
        sector="Technology",
        sector_etf="XLK",
        decision_state=CandidateDecisionState.REJECTED,
        rejection_reason="DETECTOR_REJECTED",
        feature_hash="f" * 64,
        universe_hash="u" * 64,
        data_manifest_hash="d" * 64,
        source_lineage_hash="s" * 64,
        feature_snapshot={},
        detector_candidate=None,
        listing_timestamp=ts - timedelta(days=1000),
        delisting_timestamp=None,
        sector_effective_from=ts - timedelta(days=1000),
        sector_effective_to=None,
        market_data_timestamp=ts - timedelta(minutes=1),
    )
    data.update(overrides)
    return CandidateObservation(**data)


def _result(obs):
    return PopulationBuildResult(
        decision_timestamp=obs.decision_timestamp,
        observations=(obs,),
        input_universe_count=1,
        qualified_count=0,
        rejected_count=1,
        rejection_counts={"DETECTOR_REJECTED": 1},
        universe_hash="u" * 64,
        population_hash="p" * 64,
    )


def test_population_decision_clock_is_exactly_0900_new_york():
    ts = PopulationDecisionClock().at(date(2024, 7, 10))
    assert ts.tzinfo is not None
    assert ts.astimezone(NY).hour == 9
    assert ts.astimezone(NY).minute == 0


def test_population_decision_clock_rejects_weekend():
    with pytest.raises(ValueError, match="trading day"):
        PopulationDecisionClock().at(date(2024, 7, 13))


def test_historical_member_requires_sector_effective_at_decision():
    decision = datetime(2024, 7, 10, 9, tzinfo=NY)
    member = HistoricalUniverseMember(
        stable_security_id="SEC-1",
        symbol="AAA",
        sector="Technology",
        sector_etf="XLK",
        listing_timestamp=decision - timedelta(days=1000),
        sector_effective_from=decision + timedelta(days=1),
    )
    assert member.active_at(decision)
    assert not member.sector_active_at(decision)
    assert not member.eligible_at(decision)


def test_historical_member_rejects_future_market_data_timestamp():
    decision = datetime(2024, 7, 10, 9, tzinfo=NY)
    member = HistoricalUniverseMember(
        stable_security_id="SEC-1",
        symbol="AAA",
        sector="Technology",
        sector_etf="XLK",
        listing_timestamp=decision - timedelta(days=1000),
        market_data_timestamp=decision + timedelta(minutes=1),
    )
    assert not member.eligible_at(decision)


def test_validator_reports_historical_membership_temporal_leakage():
    decision = datetime(2024, 7, 10, 9, tzinfo=NY)
    obs = _obs(decision, sector_effective_from=decision + timedelta(days=1))
    report = PopulationValidator().validate(_result(obs), expected_manifest_hash="d" * 64)
    assert not report.valid
    assert ValidationCode.TEMPORAL_LEAKAGE in {issue.code for issue in report.issues}


def test_split_registry_applies_distinct_embargo_after_boundary():
    dates = tuple(date(2024, 1, 2) + timedelta(days=i) for i in range(60))
    dates = tuple(d for d in dates if d.weekday() < 5)
    registry = SplitRegistry(
        splits=(
            TemporalSplit(kind=SplitKind.DEVELOPMENT, start=dates[0], end=dates[19]),
            TemporalSplit(kind=SplitKind.VALIDATION, start=dates[20], end=dates[35]),
        ),
        trading_dates=dates,
        purge_sessions=3,
        embargo_sessions=2,
    )
    validation = registry.purged(SplitKind.VALIDATION)
    assert validation.embargo_sessions == 2
    assert validation.excluded_dates[:2] == dates[20:22]


def test_population_manifest_records_decision_clock_contract(tmp_path):
    decision = datetime(2024, 7, 10, 9, tzinfo=NY)
    manifest = CandidatePopulationWriter().write(
        _result(_obs(decision)),
        tmp_path,
        code_commit="abc123",
        split_registry_hash="s" * 64,
    )
    assert manifest.decision_clock == "09:00 America/New_York"
