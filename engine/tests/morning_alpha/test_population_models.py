from datetime import UTC, date, datetime

import pytest

from morning_alpha.models import StrategyKey
from morning_alpha.research.population import (
    CandidateDecisionState,
    CandidateObservation,
    PopulationBuildResult,
    candidate_identity,
)


STRATEGY = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
TS = datetime(2024, 7, 10, 13, 0, tzinfo=UTC)


def _obs(**overrides):
    data = dict(
        candidate_id=candidate_identity(STRATEGY, "SEC-1", TS),
        campaign_id="morning_alpha_v1",
        strategy=STRATEGY,
        stable_security_id="SEC-1",
        symbol="AAA",
        decision_timestamp=TS,
        trading_date=date(2024, 7, 10),
        sector="Technology",
        sector_etf="XLK",
        decision_state=CandidateDecisionState.REJECTED,
        rejection_reason="DETECTOR_REJECTED",
        feature_hash="f" * 64,
        universe_hash="u" * 64,
        data_manifest_hash="d" * 64,
        source_lineage_hash="s" * 64,
        detector_candidate=None,
    )
    data.update(overrides)
    return CandidateObservation(**data)


def test_candidate_identity_is_deterministic_and_identity_sensitive():
    assert candidate_identity(STRATEGY, "SEC-1", TS) == candidate_identity(STRATEGY, "SEC-1", TS)
    assert candidate_identity(STRATEGY, "SEC-2", TS) != candidate_identity(STRATEGY, "SEC-1", TS)
    assert candidate_identity(StrategyKey(strategy_id="relative_strength_breakout", version="1.0.1"), "SEC-1", TS) != candidate_identity(STRATEGY, "SEC-1", TS)


def test_candidate_identity_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        candidate_identity(STRATEGY, "SEC-1", datetime(2024, 7, 10, 13, 0))


def test_candidate_observation_requires_trading_date_match():
    with pytest.raises(ValueError, match="trading_date"):
        _obs(trading_date=date(2024, 7, 11))


def test_population_result_rejects_duplicate_candidate_ids():
    obs = _obs()
    with pytest.raises(ValueError, match="DUPLICATE_CANDIDATE"):
        PopulationBuildResult(
            decision_timestamp=TS,
            observations=(obs, obs),
            input_universe_count=2,
            qualified_count=0,
            rejected_count=2,
            rejection_counts={"DETECTOR_REJECTED": 2},
            universe_hash="u" * 64,
            population_hash="p" * 64,
        )


def test_population_result_requires_accounting_reconciliation():
    obs = _obs()
    with pytest.raises(ValueError, match="ACCOUNTING_MISMATCH"):
        PopulationBuildResult(
            decision_timestamp=TS,
            observations=(obs,),
            input_universe_count=2,
            qualified_count=0,
            rejected_count=1,
            rejection_counts={"DETECTOR_REJECTED": 1},
            universe_hash="u" * 64,
            population_hash="p" * 64,
        )
