from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.research.execution_stress import analyze_execution_stress
from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_validation import StatisticalValidationSpec


def _row(i, *, gross=0.5, cost=0.01, slip=1.0, entry_gap=None, stop_gap=None):
    ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=f"S{i}",
        sector="Technology" if i % 2 == 0 else "Energy",
        strategy_return=0.02,
        control_return=0.0,
        gross_r=gross,
        cost_r_per_bps=cost,
        slippage_r_per_atr_fraction=slip,
        delay_penalty_r={"5s": 0.01, "30s": 0.02, "1m": 0.04, "5m": 0.08},
        entry_gap_penalty_r=entry_gap,
        stop_gap_penalty_r=stop_gap,
    )


def _spec():
    return StatisticalValidationSpec(
        min_observations=2,
        min_date_clusters=2,
        min_sector_clusters=2,
        realistic_bps=5.0,
        realistic_atr_slippage_fraction=0.02,
        realistic_delay_scenario="30s",
    )


def test_combined_realistic_stress_includes_complete_gap_penalties():
    rows = (
        _row(0, gross=0.50, entry_gap=0.03, stop_gap=0.04),
        _row(1, gross=0.30, entry_gap=0.01, stop_gap=0.02),
    )
    report = analyze_execution_stress(rows, spec=_spec())
    expected = (
        (0.50 - 0.05 - 0.02 - 0.02 - 0.03 - 0.04)
        + (0.30 - 0.05 - 0.02 - 0.02 - 0.01 - 0.02)
    ) / 2
    assert report.combined_realistic_r == pytest.approx(expected)
    assert report.gap_penalties_included is True


def test_partial_gap_evidence_is_explicitly_invalid_not_zero_filled():
    rows = (
        _row(0, entry_gap=0.03, stop_gap=0.04),
        _row(1, entry_gap=None, stop_gap=0.02),
    )
    report = analyze_execution_stress(rows, spec=_spec())
    assert "ENTRY_GAP_EVIDENCE_PARTIAL" in report.reasons
    assert report.combined_realistic_r is None


def test_no_gap_evidence_remains_valid_and_does_not_invent_gap_costs():
    rows = (_row(0), _row(1))
    report = analyze_execution_stress(rows, spec=_spec())
    assert report.gap_penalties_included is False
    assert not any("GAP_EVIDENCE" in reason for reason in report.reasons)
