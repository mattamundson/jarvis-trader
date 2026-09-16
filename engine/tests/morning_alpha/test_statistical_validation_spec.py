from datetime import UTC, datetime

import pytest

from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_validation import StatisticalValidationSpec


def _row(**updates):
    ts = datetime(2024, 7, 10, 13, 0, tzinfo=UTC)
    data = dict(
        candidate_id="c-1",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol="AAA",
        sector="Technology",
        strategy_return=0.02,
        control_return=0.01,
    )
    data.update(updates)
    return MatchedEdgeObservation(**data)


def test_statistical_validation_spec_defaults_are_frozen():
    spec = StatisticalValidationSpec()
    assert spec.min_observations == 200
    assert spec.min_date_clusters == 30
    assert spec.min_sector_clusters == 3
    assert spec.confidence == 0.95
    assert spec.bootstrap_resamples == 10_000
    assert spec.permutation_resamples == 10_000
    assert spec.cost_bps == (0, 2, 5, 10, 20)
    assert spec.atr_slippage_fractions == (0.0, 0.02, 0.05, 0.10)
    assert spec.delay_scenarios == ("5s", "30s", "1m", "5m")
    assert spec.realistic_bps == 5.0
    assert spec.realistic_atr_slippage_fraction == 0.02
    assert spec.realistic_delay_scenario == "30s"


def test_statistical_validation_spec_rejects_unknown_realistic_delay_scenario():
    with pytest.raises(ValueError, match="realistic_delay_scenario"):
        StatisticalValidationSpec(realistic_delay_scenario="10m")


def test_matched_observation_accepts_execution_evidence():
    row = _row(
        gross_r=0.4,
        cost_r_per_bps=0.01,
        slippage_r_per_atr_fraction=1.5,
        delay_penalty_r={"5s": 0.01, "30s": 0.03, "1m": 0.06, "5m": 0.10},
        entry_gap_penalty_r=0.02,
        stop_gap_penalty_r=0.04,
    )
    assert row.slippage_r_per_atr_fraction == 1.5
    assert row.delay_penalty_r["30s"] == 0.03


def test_matched_observation_rejects_non_finite_execution_coefficients():
    with pytest.raises(ValueError, match="slippage_r_per_atr_fraction"):
        _row(slippage_r_per_atr_fraction=float("inf"))


def test_matched_observation_rejects_non_finite_delay_penalty():
    with pytest.raises(ValueError, match="delay_penalty_r"):
        _row(delay_penalty_r={"30s": float("nan")})


def test_matched_observation_rejects_blank_delay_scenario():
    with pytest.raises(ValueError, match="delay_penalty_r key"):
        _row(delay_penalty_r={"": 0.1})
