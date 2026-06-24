"""
Tests for the Monte Carlo Permutation Test CLI (backtest.run_mcpt).

Covers the pure statistical primitives (sign-flip randomization, bootstrap CI,
OHLC bar-return permutation, the prices-MCPT counting loop) plus the DB
trade-PnL loader. The heavy strategy/Backtester is injected as a callable so
these tests stay fast and deterministic.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.run_mcpt import (
    bootstrap_test,
    load_trade_pnls,
    permute_ohlc,
    prices_mcpt,
    prices_mcpt_optimized,
    profit_factor,
    signflip_test,
)

# ---------------------------------------------------------------------------
# profit_factor
# ---------------------------------------------------------------------------


def test_profit_factor_basic():
    pnls = np.array([10.0, -5.0, 20.0, -5.0])
    # gross profit = 30, gross loss = 10 -> 3.0
    assert profit_factor(pnls) == pytest.approx(3.0)


def test_profit_factor_no_losses_is_inf():
    assert profit_factor(np.array([10.0, 5.0])) == float("inf")


def test_profit_factor_no_profits_is_zero():
    assert profit_factor(np.array([-10.0, -5.0])) == 0.0


# ---------------------------------------------------------------------------
# sign-flip randomization test
# ---------------------------------------------------------------------------


def test_signflip_strong_positive_edge_low_pvalue():
    # All-positive PnL: observed mean is the maximum achievable under any sign
    # flip, so almost no permutation matches/beats it -> p-value near the floor.
    pnls = np.array([5.0, 7.0, 6.0, 8.0, 4.0, 9.0, 5.0, 6.0])
    res = signflip_test(pnls, n_resamples=2000, seed=42)
    assert res["p_value_mean"] < 0.05
    assert res["observed_mean"] == pytest.approx(np.mean(pnls))
    assert res["n_trades"] == 8


def test_signflip_no_edge_high_pvalue():
    # Symmetric PnL -> observed mean is 0, so ~half of sign-flips meet or beat
    # it. p-value should be large (nowhere near significant).
    pnls = np.array([10.0, -10.0, 10.0, -10.0, 10.0, -10.0])
    res = signflip_test(pnls, n_resamples=2000, seed=42)
    assert res["p_value_mean"] > 0.2


def test_signflip_reproducible_with_seed():
    pnls = np.array([3.0, -1.0, 4.0, -2.0, 5.0])
    a = signflip_test(pnls, n_resamples=1000, seed=7)
    b = signflip_test(pnls, n_resamples=1000, seed=7)
    assert a == b


def test_signflip_pvalue_in_unit_interval():
    pnls = np.array([3.0, -1.0, 4.0, -2.0, 5.0])
    res = signflip_test(pnls, n_resamples=500, seed=1)
    assert 0.0 < res["p_value_mean"] <= 1.0
    assert 0.0 < res["p_value_pf"] <= 1.0


# ---------------------------------------------------------------------------
# bootstrap CI test
# ---------------------------------------------------------------------------


def test_bootstrap_ci_ordered_and_brackets_observed():
    pnls = np.array([5.0, 7.0, 6.0, -2.0, 8.0, 4.0, -1.0, 6.0, 5.0, 7.0])
    res = bootstrap_test(pnls, n_resamples=2000, seed=42)
    assert res["pf_ci_lower"] <= res["pf_ci_upper"]
    assert res["mean_ci_lower"] <= res["observed_mean"] <= res["mean_ci_upper"]


def test_bootstrap_strong_edge_low_pf_le_1_probability():
    # Strongly profitable -> bootstrap rarely produces PF <= 1.0.
    pnls = np.array([5.0, 7.0, 6.0, 8.0, 4.0, 9.0, -1.0, 6.0, 5.0, 7.0])
    res = bootstrap_test(pnls, n_resamples=2000, seed=42)
    assert res["p_value_pf_le_1"] < 0.05


def test_bootstrap_reproducible_with_seed():
    pnls = np.array([3.0, -1.0, 4.0, -2.0, 5.0, 1.0])
    a = bootstrap_test(pnls, n_resamples=800, seed=11)
    b = bootstrap_test(pnls, n_resamples=800, seed=11)
    assert a == b


# ---------------------------------------------------------------------------
# OHLC bar-return permutation
# ---------------------------------------------------------------------------


def _make_ohlc(n=200, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.01, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def test_permute_ohlc_preserves_shape_and_index():
    df = _make_ohlc(120, seed=3)
    perm = permute_ohlc(df, seed=42)
    assert list(perm.columns) == ["open", "high", "low", "close"]
    assert len(perm) == len(df)
    assert perm.index.equals(df.index)


def test_permute_ohlc_first_bar_anchored():
    df = _make_ohlc(120, seed=3)
    perm = permute_ohlc(df, seed=42)
    for col in ("open", "high", "low", "close"):
        assert perm[col].iloc[0] == pytest.approx(df[col].iloc[0])


def test_permute_ohlc_preserves_ohlc_validity():
    df = _make_ohlc(150, seed=5)
    perm = permute_ohlc(df, seed=42)
    assert (perm["high"] >= perm["open"] - 1e-9).all()
    assert (perm["high"] >= perm["close"] - 1e-9).all()
    assert (perm["high"] >= perm["low"] - 1e-9).all()
    assert (perm["low"] <= perm["open"] + 1e-9).all()
    assert (perm["low"] <= perm["close"] + 1e-9).all()


def test_permute_ohlc_preserves_final_close():
    # Total log return = sum of gaps + intrabar close offsets, both invariant
    # under permutation -> the synthetic series ends at the same price.
    df = _make_ohlc(200, seed=7)
    perm = permute_ohlc(df, seed=99)
    assert perm["close"].iloc[-1] == pytest.approx(df["close"].iloc[-1], rel=1e-6)


def test_permute_ohlc_actually_shuffles():
    df = _make_ohlc(200, seed=7)
    perm = permute_ohlc(df, seed=99)
    # The interior path must differ from the original (not an identity map).
    assert not np.allclose(perm["close"].values, df["close"].values)


def test_permute_ohlc_reproducible_with_seed():
    df = _make_ohlc(100, seed=1)
    a = permute_ohlc(df, seed=42)
    b = permute_ohlc(df, seed=42)
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------------------
# prices-MCPT counting loop (strategy injected)
# ---------------------------------------------------------------------------


def test_prices_mcpt_constant_strategy_gives_pvalue_one():
    # If the strategy returns the same PF on every (permuted) series, every
    # permutation ties the observed value -> p = (1 + N) / (N + 1) = 1.0.
    df = _make_ohlc(80, seed=2)

    def run_fn(_df):
        return type("R", (), {"profit_factor": 2.0})()

    res = prices_mcpt(df, run_fn, n_resamples=50, seed=42)
    assert res["p_value"] == pytest.approx(1.0)
    assert res["n_resamples"] == 50
    assert res["observed_pf"] == pytest.approx(2.0)


def test_prices_mcpt_real_edge_gives_floor_pvalue():
    # Strategy returns a high PF only on the original object and a low PF on
    # every permutation -> p = (1 + 0) / (N + 1).
    df = _make_ohlc(80, seed=2)

    def run_fn(d):
        return type("R", (), {"profit_factor": 5.0 if d is df else 1.0})()

    res = prices_mcpt(df, run_fn, n_resamples=99, seed=42)
    assert res["observed_pf"] == pytest.approx(5.0)
    assert res["p_value"] == pytest.approx(1.0 / 100.0)


def test_prices_mcpt_reproducible_with_seed():
    df = _make_ohlc(80, seed=2)
    calls = {"n": 0}

    def run_fn(d):
        calls["n"] += 1
        return type("R", (), {"profit_factor": float(d["close"].iloc[-1])})()

    a = prices_mcpt(df, run_fn, n_resamples=30, seed=5)
    b = prices_mcpt(df, run_fn, n_resamples=30, seed=5)
    assert a["p_value"] == b["p_value"]


# ---------------------------------------------------------------------------
# DB trade-PnL loader
# ---------------------------------------------------------------------------


def _make_trades_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            pnl REAL,
            status TEXT
        )
        """
    )
    rows = [
        ("MES", 100.0, "closed"),
        ("MES", -50.0, "closed"),
        ("MES", None, "open"),  # open, no pnl -> excluded
        ("MGC", 25.0, "closed"),  # other symbol -> excluded for MES
        ("MES", 75.0, "closed"),
    ]
    conn.executemany("INSERT INTO paper_trades (symbol, pnl, status) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_load_trade_pnls_filters_symbol_and_null(tmp_path):
    db = tmp_path / "t.db"
    _make_trades_db(db)
    pnls = load_trade_pnls(str(db), "MES")
    assert sorted(pnls.tolist()) == [-50.0, 75.0, 100.0]


def test_load_trade_pnls_empty_for_unknown_symbol(tmp_path):
    db = tmp_path / "t.db"
    _make_trades_db(db)
    pnls = load_trade_pnls(str(db), "ZZZZ")
    assert len(pnls) == 0


# ---------------------------------------------------------------------------
# optimization-aware prices-MCPT (v2: re-run grid selection per permutation)
# ---------------------------------------------------------------------------


def test_prices_mcpt_optimized_constant_gives_pvalue_one():
    # Every param on every series scores the same -> observed best ties all
    # permuted bests -> p = 1.0.
    df = _make_ohlc(80, seed=2)
    grid = [(50, 200), (55, 200), (60, 200)]

    def run_param_fn(_df, _params):
        return type("R", (), {"profit_factor": 2.0})()

    res = prices_mcpt_optimized(df, run_param_fn, grid, n_resamples=40, seed=42)
    assert res["p_value"] == pytest.approx(1.0)
    assert res["observed_best_pf"] == pytest.approx(2.0)
    assert res["n_resamples"] == 40


def test_prices_mcpt_optimized_selects_best_param():
    # Best-over-grid must pick the max-PF param on the real series.
    df = _make_ohlc(80, seed=2)
    grid = [(50, 200), (55, 200), (60, 200)]
    pf_by_fast = {50: 1.5, 55: 3.0, 60: 2.0}

    def run_param_fn(d, params):
        pf = pf_by_fast[params[0]] if d is df else 0.5
        return type("R", (), {"profit_factor": pf})()

    res = prices_mcpt_optimized(df, run_param_fn, grid, n_resamples=30, seed=42)
    assert res["observed_best_pf"] == pytest.approx(3.0)
    assert res["best_params"] == (55, 200)
    # observed best (3.0) beats every permuted best (0.5) -> floor p-value.
    assert res["p_value"] == pytest.approx(1.0 / 31.0)


def test_prices_mcpt_optimized_reproducible_with_seed():
    df = _make_ohlc(80, seed=2)
    grid = [(50, 200), (60, 200)]

    def run_param_fn(d, params):
        return type("R", (), {"profit_factor": float(d["close"].iloc[-1]) + params[0]})()

    a = prices_mcpt_optimized(df, run_param_fn, grid, n_resamples=20, seed=5)
    b = prices_mcpt_optimized(df, run_param_fn, grid, n_resamples=20, seed=5)
    assert a["p_value"] == b["p_value"]
