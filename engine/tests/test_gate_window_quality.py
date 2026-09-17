"""Tests for `_gate_v2_helpers.window_quality` — the honest p_edge decomposition.

Context (2026-09-17): 37 runners override the gate-standard
`MIN_OOS_TRADES_PER_WINDOW` (5) down to 1 with explicit reasoning — SMA trend
strategies fire only 1-3 trades per 2-month OOS window, so a 5-trade floor yields
`INSUFFICIENT_SAMPLE` across the board. The consequence is that `p_edge` is computed
over windows that cannot distinguish edge from a coin flip: for
`MES_sma_trend_vix_pctile_blockCrisis_v1` the verdict read `p_edge = 0.5926` while 29 of
its 32 "profitable" windows held a single trade (PF = `inf`) and the multi-trade subset
was 3/25 = 0.12.

`window_quality` is additive — it must never change a pass/fail decision. These tests
pin the arithmetic, the direction of the correction, and the fact that the runner's own
`p_edge` is reported unchanged alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backtest._gate_v2_helpers import MIN_OOS_TRADES_PER_WINDOW, window_quality


@dataclass
class _Window:
    """Minimal stand-in for a BacktestResult; only these two fields are read."""

    total_trades: int
    profit_factor: float


def _rows(spec: list[tuple[int, float]]) -> list[_Window]:
    return [_Window(t, pf) for t, pf in spec]


def test_gate_standard_floor_is_five():
    """The helper defaults to the gate standard, not a runner-local override."""
    wq = window_quality(_rows([(1, float("inf"))]))
    assert wq["gate_min_trades"] == MIN_OOS_TRADES_PER_WINDOW == 5


def test_degenerate_single_trade_windows_are_exposed():
    """A p_edge carried by 1-trade windows must collapse when they are excluded.

    Mirrors the real MES VIX-pctile distribution shape: mostly single-trade
    winners, a handful of windows with real samples.
    """
    spec = [(1, float("inf"))] * 29 + [(2, 0.5), (3, 0.4), (4, 0.3), (6, 1.9), (7, 1.1)]
    wq = window_quality(_rows(spec))

    assert wq["n_windows_with_trades"] == 34
    assert wq["n_windows_single_trade"] == 29
    # 31 of 34 windows have PF > 1.0 (the 29 inf windows plus the two real winners)
    assert wq["p_edge"] == round(31 / 34, 4)
    # only the 2 windows with >= 2 trades and PF > 1.0 survive
    assert wq["p_edge_excl_single_trade"] == round(2 / 5, 4)
    assert wq["p_edge_at_gate_floor"] == round(2 / 2, 4)


def test_reported_p_edge_is_unchanged_by_the_decomposition():
    """The runner's existing number must pass through untouched (additive contract)."""
    spec = [(1, float("inf")), (2, 2.0), (5, 0.5)]
    wq = window_quality(_rows(spec))
    expected = sum(1 for _, pf in spec if pf > 1.0) / len(spec)
    assert wq["p_edge"] == round(expected, 4)  # 2/3, unchanged
    assert wq["n_windows_at_gate_floor"] == 1
    # the only floor-qualifying window LOST, so the honest number is 0.0
    assert wq["p_edge_at_gate_floor"] == 0.0


def test_inf_is_treated_as_profitable_matching_the_runners():
    """`inf` (one winning trade) counts as > 1.0 — this is the runner's definition."""
    wq = window_quality(_rows([(1, float("inf")), (1, 0.0)]))
    assert wq["p_edge"] == 0.5


def test_zero_trade_windows_are_not_counted_as_traded():
    wq = window_quality(_rows([(0, 0.0), (0, 0.0), (2, 1.5)]))
    assert wq["n_windows"] == 3
    assert wq["n_windows_with_trades"] == 1
    assert wq["n_windows_single_trade"] == 0
    # p_edge denominator follows the runner: pfs are filtered to >= 1 trade
    assert wq["p_edge"] == 1.0


def test_median_and_adequacy_use_the_gate_floor():
    adequate = window_quality(_rows([(5, 1.5), (6, 1.4), (5, 1.2)]))
    assert adequate["median_trades_per_window"] == 5.0
    assert adequate["sample_adequate_at_gate_floor"] is True

    inadequate = window_quality(_rows([(1, float("inf")), (1, float("inf")), (5, 1.2)]))
    assert inadequate["median_trades_per_window"] == 1.0
    assert inadequate["sample_adequate_at_gate_floor"] is False


def test_empty_and_none_inputs_are_safe():
    for empty in ([], None):
        wq = window_quality(empty)
        assert wq["n_windows"] == 0
        assert wq["p_edge"] == 0.0
        assert wq["p_edge_excl_single_trade"] == 0.0
        assert wq["median_trades_per_window"] == 0.0


@pytest.mark.parametrize("floor", [1, 2, 3, 5, 10])
def test_floor_is_configurable_for_family_standards(floor: int):
    wq = window_quality(_rows([(3, 1.5), (10, 1.2)]), gate_min_trades=floor)
    assert wq["gate_min_trades"] == floor
    expected = sum(1 for t, pf in [(3, 1.5), (10, 1.2)] if t >= floor and pf > 1.0) / sum(
        1 for t, _ in [(3, 1.5), (10, 1.2)] if t >= floor
    )
    assert wq["p_edge_at_gate_floor"] == round(expected, 4)
