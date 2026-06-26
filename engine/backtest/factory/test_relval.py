"""Tests for the relative-value (pairs) backtester."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.factory.relval import (
    Pair,
    backtest_spread,
    build_spread,
    relval_gauntlet,
    relval_pairs,
    smoke_test_pair,
    spread_trade_dollars,
)


def test_pairs_are_pre_registered_with_rationale():
    pairs = relval_pairs()
    names = {p.name for p in pairs}
    # equity crosses + the pre-registered rates-curve pair (1:1 and DV01-neutral)
    assert {"MES_MNQ", "MES_M2K", "MNQ_M2K", "ES_NQ", "ZB_ZN", "ZB_ZN_DV01"} <= names
    # rationale gate: no blank / trivial rationale (pre-registration vs p-hacking)
    for p in pairs:
        assert len(p.economic_rationale) >= 25
        assert p.leg_a != p.leg_b  # never a same-instrument self-pair


def _series(arr) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=len(arr), freq="h")
    return pd.Series(arr, index=idx)


def _cointegrated_frames(months=15, seed=3):
    """Two `close` DataFrames over real calendar time so WFO windows can form.
    B is a random walk; A = B + a mean-reverting OU deviation -> the log spread
    mean-reverts, so the gauntlet should run the full path (not early-out)."""
    idx = pd.date_range("2024-06-01", periods=months * 30 * 24, freq="h")
    n = len(idx)
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.01, n))
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = ou[t - 1] * 0.97 + rng.normal(0, 0.02)
    a = pd.DataFrame({"close": np.exp(common + ou)}, index=idx)
    b = pd.DataFrame({"close": np.exp(common)}, index=idx)
    return a, b


def _test_pair():
    return Pair(
        name="TEST",
        leg_a="A",
        leg_b="B",
        economic_rationale="synthetic cointegrated OU pair for harness validation only",
        timeframes=["1h"],
        default_params={"window": 60, "entry_z": 2.0, "exit_z": 0.5, "stop_z": 4.0},
        param_grid={"window": [40, 60, 120], "entry_z": [1.5, 2.0, 2.5], "exit_z": [0.25, 0.5]},
    )


def _cointegrated(n=4000, seed=1):
    """B is a random walk; A = B plus a mean-reverting (OU) deviation. So
    log(A)-log(B) mean-reverts -> z-score reversion should profit."""
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.01, n))
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = ou[t - 1] * 0.95 + rng.normal(0, 0.02)  # mean-reverting deviation
    a = np.exp(common + ou)
    b = np.exp(common)
    return _series(a), _series(b)


def _random_walk_pair(n=4000, seed=2):
    """Two independent random walks -> spread is itself a random walk (no reversion)."""
    rng = np.random.default_rng(seed)
    a = np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    b = np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return _series(a), _series(b)


def test_build_spread_no_lookahead():
    a, b = _cointegrated(500)
    sp = build_spread(a, b, window=60)
    # first `window` z-values must be NaN (rolling+shift warm-up) -> no peeking
    assert sp["z"].iloc[:60].isna().all()
    assert sp["z"].iloc[100:].notna().any()


def test_cointegrated_pair_is_profitable():
    a, b = _cointegrated()
    m = backtest_spread(a, b, window=60, entry_z=2.0, exit_z=0.5, cost_bps_per_leg=0.5)
    assert m.total_trades >= 10
    assert m.profit_factor > 1.2, f"reversion edge should be profitable, got pf={m.profit_factor}"


def test_random_walk_pair_has_no_edge():
    a, b = _random_walk_pair()
    m = backtest_spread(a, b, window=60, entry_z=2.0, exit_z=0.5, cost_bps_per_leg=1.0)
    # no genuine reversion -> profit factor should not show a real edge
    assert m.profit_factor < 1.5


def test_returns_metrics_contract():
    a, b = _cointegrated(1000)
    m = backtest_spread(a, b)
    assert hasattr(m, "profit_factor") and hasattr(m, "sharpe_ratio")
    assert hasattr(m, "max_drawdown_pct") and hasattr(m, "total_trades")


def test_thin_data_returns_zero_trades():
    a, b = _cointegrated(40)
    m = backtest_spread(a, b, window=60)
    assert m.total_trades == 0


def test_smoke_test_pair_contract():
    a, b = _cointegrated_frames()
    survives, info = smoke_test_pair(_test_pair(), a, b, "1h")
    assert info["stage"] == "smoke"
    assert {"pre_sharpe", "pre_pf", "trades", "low_sample"} <= info.keys()
    assert isinstance(survives, bool)


def test_gauntlet_returns_full_gate_dict():
    a, b = _cointegrated_frames()
    pair = _test_pair()
    gate = relval_gauntlet(pair, a, b, "1h", global_trial_count=660)
    # full path exercised -> the multiple-testing wiring must be present
    assert gate["n_grid_combos"] == pair.n_param_combos()
    assert gate["global_trial_count"] == 660
    assert "dsr_global" in gate and isinstance(gate["dsr_global"], float)
    assert "pbo" in gate
    assert "verdict" in gate
    # UNITS REGRESSION: mc_95th_dd is a FRACTION (0.05 == 5%), not a percent.
    # A 100x units error here inflates it to ~145 and fails every pair.
    assert 0.0 <= gate["mc_95th_dd"] <= 1.0, f"dd must be a fraction, got {gate['mc_95th_dd']}"
    # DSR comes from the real per-trade distribution deflated by 660 trials -> a
    # valid probability, never the fake 1.0 the window-mean-Sharpe path produced.
    assert 0.0 <= gate["dsr"] <= 1.0


def test_backtest_spread_drawdown_is_a_fraction():
    a, b = _cointegrated()
    m = backtest_spread(a, b, window=60, entry_z=2.0, exit_z=0.5)
    # capital-relative drawdown fraction, not a 0-200 percent
    assert 0.0 <= m.max_drawdown_pct <= 1.0


def test_spread_trade_dollars_scale():
    a, b = _cointegrated(1000)
    dollars = spread_trade_dollars(a, b, window=60)
    assert len(dollars) >= 5
    # USD PnLs on a $50K-per-leg book -- finite, signed, not return-unit tiny
    assert all(abs(d) < 50_000 for d in dollars)
    assert any(d != 0 for d in dollars)


def test_gauntlet_thin_data_fails_early():
    idx = pd.date_range("2025-01-01", periods=200, freq="h")
    a = pd.DataFrame({"close": np.linspace(100, 101, 200)}, index=idx)
    b = pd.DataFrame({"close": np.linspace(100, 100.5, 200)}, index=idx)
    gate = relval_gauntlet(_test_pair(), a, b, "1h", global_trial_count=660)
    assert gate["verdict"] == "FAIL"
    assert "insufficient" in gate["reason"] or "no OOS" in gate["reason"]
