from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.research.execution_stress import analyze_execution_stress
from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_validation import StatisticalValidationSpec


def _row(i, *, gross=0.4, cost=0.01, slip=1.0, delays=None, entry_gap=None, stop_gap=None):
    ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=f"S{i}",
        sector="Technology",
        strategy_return=0.01,
        control_return=0.0,
        gross_r=gross,
        cost_r_per_bps=cost,
        slippage_r_per_atr_fraction=slip,
        delay_penalty_r=delays or {"5s": 0.01, "30s": 0.03, "1m": 0.05, "5m": 0.10},
        entry_gap_penalty_r=entry_gap,
        stop_gap_penalty_r=stop_gap,
    )


def _spec(**updates):
    data = dict(
        min_observations=2,
        min_date_clusters=2,
        min_sector_clusters=2,
        realistic_bps=5.0,
        realistic_atr_slippage_fraction=0.02,
        realistic_delay_scenario="30s",
    )
    data.update(updates)
    return StatisticalValidationSpec(**data)


def test_cost_curve_uses_per_observation_coefficients():
    rows = (_row(0, gross=0.5, cost=0.01), _row(1, gross=0.3, cost=0.02))
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.cost_curve_r[0] == pytest.approx(0.4)
    assert report.cost_curve_r[20] == pytest.approx(((0.5 - 0.2) + (0.3 - 0.4)) / 2)
    assert report.break_even_bps == pytest.approx(0.4 / 0.015)


def test_atr_break_even_solves_mean_net_zero():
    rows = (_row(0, gross=0.4, slip=1.0), _row(1, gross=0.2, slip=0.5))
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.break_even_atr_fraction == pytest.approx(0.3 / 0.75)
    assert report.atr_slippage_curve_r[0.10] == pytest.approx(((0.4 - 0.10) + (0.2 - 0.05)) / 2)


def test_delay_stress_aggregates_supplied_penalties():
    rows = (
        _row(0, gross=0.4, delays={"5s": 0.01, "30s": 0.02, "1m": 0.03, "5m": 0.08}),
        _row(1, gross=0.2, delays={"5s": 0.02, "30s": 0.04, "1m": 0.05, "5m": 0.10}),
    )
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.delay_curve_r["30s"] == pytest.approx(((0.4 - 0.02) + (0.2 - 0.04)) / 2)


def test_combined_realistic_stress_applies_all_penalties_per_observation():
    rows = (
        _row(0, gross=0.5, cost=0.01, slip=1.0, delays={"5s": 0.01, "30s": 0.02, "1m": 0.03, "5m": 0.08}),
        _row(1, gross=0.3, cost=0.02, slip=0.5, delays={"5s": 0.02, "30s": 0.04, "1m": 0.05, "5m": 0.10}),
    )
    report = analyze_execution_stress(rows, spec=_spec())
    expected = ((0.5 - 0.05 - 0.02 - 0.02) + (0.3 - 0.10 - 0.01 - 0.04)) / 2
    assert report.combined_realistic_r == pytest.approx(expected)


def test_gap_penalties_are_reported_without_being_silently_zero_filled():
    rows = (_row(0, entry_gap=0.03, stop_gap=0.05), _row(1, entry_gap=0.01, stop_gap=0.03))
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.mean_entry_gap_penalty_r == pytest.approx(0.02)
    assert report.mean_stop_gap_penalty_r == pytest.approx(0.04)


def test_missing_slippage_or_delay_evidence_blocks_combined_stress():
    rows = (
        _row(0, slip=None),
        _row(1, delays={"5s": 0.01}),
    )
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.combined_realistic_r is None
    assert "SLIPPAGE_EVIDENCE_MISSING" in report.reasons
    assert "DELAY_EVIDENCE_MISSING:30s" in report.reasons
