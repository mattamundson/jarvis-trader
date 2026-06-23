"""Tests for the cost-drag decomposition analyzer.

The pure logic that matters is the classification of a FAILing family into
NO_EDGE (no gross edge -> abandon) vs COST_KILLED (real gross edge eaten by cost
-> pursue better execution) vs ROBUST (clears even net), plus the cost-injecting
run_fn wrapper that forces a uniform cost tier across an entire WFO grid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from backtest.cost_drag_analysis import (
    GATE_PF_CI_LOWER,
    REALISTIC_COST,
    ZERO_COST,
    _cost_injecting_run_fn,
    _load_champion,
    _oos_pf_ci,
    classify_cost_drag,
)


# --- classify_cost_drag -----------------------------------------------------
def test_no_edge_when_gross_below_threshold():
    # Even at zero cost the signal can't clear 1.10 -> abandon the family.
    assert classify_cost_drag(gross_pf_ci=0.80, net_pf_ci=0.55) == "NO_EDGE"


def test_cost_killed_when_gross_clears_but_net_fails():
    # A real gross edge (>=1.10) that costs drag below threshold -> execution lever.
    assert classify_cost_drag(gross_pf_ci=1.35, net_pf_ci=0.90) == "COST_KILLED"


def test_robust_when_net_already_clears():
    # Net (realistic-cost) already clears -> not actually cost-limited.
    assert classify_cost_drag(gross_pf_ci=1.60, net_pf_ci=1.25) == "ROBUST"


def test_threshold_is_inclusive_for_gross():
    # gross exactly at the floor counts as a (cost-killed) edge, not NO_EDGE.
    assert classify_cost_drag(gross_pf_ci=GATE_PF_CI_LOWER, net_pf_ci=0.70) == "COST_KILLED"


def test_threshold_is_inclusive_for_net():
    # net exactly at the floor is ROBUST (clears the gate threshold).
    assert classify_cost_drag(gross_pf_ci=2.0, net_pf_ci=GATE_PF_CI_LOWER) == "ROBUST"


def test_custom_threshold_overrides_default():
    assert classify_cost_drag(gross_pf_ci=1.05, net_pf_ci=0.9, threshold=1.0) == "COST_KILLED"


# --- _cost_injecting_run_fn -------------------------------------------------
def test_cost_injecting_run_fn_overrides_cost_keys():
    captured = {}

    def base(df, params):
        captured.update(params)
        return "result"

    wrapped = _cost_injecting_run_fn(base, ZERO_COST)
    out = wrapped("DF", {"fast": 8, "slow": 24, "commission": 0.62, "slippage_ticks": 2.0})

    assert out == "result"
    # signal params preserved, cost keys forced to the injected (zero) tier
    assert captured["fast"] == 8 and captured["slow"] == 24
    assert captured["commission"] == 0.0
    assert captured["slippage_ticks"] == 0.0


def test_cost_injecting_run_fn_realistic_tier():
    captured = {}

    def base(df, params):
        captured.update(params)
        return None

    _cost_injecting_run_fn(base, REALISTIC_COST)("DF", {"fast": 8})
    assert captured["commission"] == 0.62
    assert captured["slippage_ticks"] == 2.0


# --- _oos_pf_ci -------------------------------------------------------------
@dataclass
class _FakeOOS:
    total_trades: int
    profit_factor: float


def test_oos_pf_ci_filters_thin_windows_and_sums_trades():
    # Two qualifying windows (PF 2.0 each, well above 1.0) + one thin window
    # below min_trades that is excluded from the PF CI but still counted in trades.
    oos = [_FakeOOS(10, 2.0), _FakeOOS(10, 2.0), _FakeOOS(1, 0.1)]
    pf_ci, total = _oos_pf_ci(oos, min_trades=3)
    assert total == 21  # all trades counted
    assert pf_ci > 1.0  # CI of two strong windows is positive


def test_oos_pf_ci_empty_returns_zero():
    pf_ci, total = _oos_pf_ci([], min_trades=3)
    assert pf_ci == 0.0
    assert total == 0


def test_oos_pf_ci_all_thin_returns_zero_pf_but_counts_trades():
    oos = [_FakeOOS(1, 5.0), _FakeOOS(2, 5.0)]
    pf_ci, total = _oos_pf_ci(oos, min_trades=3)
    assert pf_ci == 0.0  # no window qualifies -> no PF CI
    assert total == 3


# --- _load_champion ---------------------------------------------------------
def test_load_champion_reads_params_from_verdict(tmp_path):
    (tmp_path / "MES_sma_trend_15m.json").write_text(
        json.dumps({"champion_params": {"fast": 16, "slow": 48, "atr_trail_mult": 2.5}})
    )
    champ = _load_champion("MES_sma_trend_15m", factory_dir=tmp_path)
    assert champ == {"fast": 16, "slow": 48, "atr_trail_mult": 2.5}


def test_load_champion_missing_file_returns_none(tmp_path):
    assert _load_champion("NOPE_label", factory_dir=tmp_path) is None


def test_load_champion_malformed_json_returns_none(tmp_path):
    (tmp_path / "BAD.json").write_text("{not valid json")
    assert _load_champion("BAD", factory_dir=tmp_path) is None
