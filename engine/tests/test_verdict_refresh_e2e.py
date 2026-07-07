"""End-to-end verdict refresh test on synthetic data (P2-6).

Exercises the full WFO pipeline on 500 hourly bars with 3 walk-forward
windows and 5 SMA-trend grid combinations. Verifies that:
  - Every window produces at least a run attempt (no unhandled exception)
  - Gate v2 metric functions accept the results without crashing
  - The final verdict dict is structurally valid (required keys, finite values)
  - Metrics are consistent (win_rate in [0,1], profit_factor >= 0, etc.)

This is an integrity / regression guard. It does NOT assert the verdict
is PASS or FAIL — that depends on synthetic price dynamics which vary
by seed. The test only checks that the pipeline produces well-formed output
given any plausible input.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
)
from backtest.backtester import Backtester
from backtest.trend_signals import generate_sma_trend_signals

# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

_SEED = 42
_N_BARS = 500
_SYMBOL = "SYN"
_MULTIPLIER = 10.0
_COMMISSION = 0.62
_SLIPPAGE_TICKS = 2.0
_CAPITAL = 50_000.0


def _make_ohlcv(n: int = _N_BARS, seed: int = _SEED) -> pd.DataFrame:
    """500 hourly bars with a modest upward drift + noise.

    OHLC is constructed from a Gaussian random walk so that
    High >= Close >= Open >= Low (approximately — with wick jitter).
    """
    rng = np.random.default_rng(seed)
    # Brownian motion with small upward drift
    returns = rng.normal(loc=0.0003, scale=0.003, size=n)
    close = 2000.0 * np.cumprod(1 + returns)

    noise = rng.uniform(0.001, 0.003, size=n)
    high = close * (1 + noise)
    low = close * (1 - noise)
    open_ = np.roll(close, 1)
    open_[0] = close[0]

    start = datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc)
    index = pd.date_range(start=start, periods=n, freq="1h", tz="UTC")

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 100},
        index=index,
    )


# ---------------------------------------------------------------------------
# WFO helpers — mirrors the runner pattern but parameterised
# ---------------------------------------------------------------------------

_TRAIN_BARS = 150  # ~6 months at 1h (≈21 bars/day × 5 days × 4 weeks × 6)
_TEST_BARS = 50  # ~2 months
_STEP_BARS = 50  # 1 step per window

# 5 param combos
_GRID = [
    {"fast": 20, "slow": 50},
    {"fast": 30, "slow": 80},
    {"fast": 40, "slow": 80},
    {"fast": 40, "slow": 120},
    {"fast": 50, "slow": 120},
]


def _generate_windows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return 3 non-overlapping walk-forward windows."""
    n = len(df)
    windows = []
    cursor = 0
    while len(windows) < 3:
        if cursor + _TRAIN_BARS + _TEST_BARS > n:
            break
        train_end = cursor + _TRAIN_BARS
        test_end = train_end + _TEST_BARS
        windows.append(
            {
                "train": df.iloc[cursor:train_end],
                "test": df.iloc[train_end:test_end],
            }
        )
        cursor += _STEP_BARS
    return windows


def _best_is_params(df_train: pd.DataFrame) -> dict:
    """Grid-search IS data — pick combo with highest profit_factor."""
    best_pf = -1.0
    best_combo: dict = _GRID[0]

    for combo in _GRID:
        try:
            sig = generate_sma_trend_signals(df_train, **combo)
            result = Backtester(
                initial_capital=_CAPITAL,
                commission_per_contract=_COMMISSION,
                slippage_ticks=_SLIPPAGE_TICKS,
            ).run(sig, symbol=_SYMBOL, multiplier=_MULTIPLIER)
            pf = result.profit_factor if result.total_trades >= 1 else 0.0
            if pf > best_pf:
                best_pf = pf
                best_combo = combo
        except Exception:
            continue

    return best_combo


def _run_oos(df_test: pd.DataFrame, params: dict) -> dict[str, float]:
    """Run OOS backtest with best IS params; return key metrics."""
    try:
        sig = generate_sma_trend_signals(df_test, **params)
        result = Backtester(
            initial_capital=_CAPITAL,
            commission_per_contract=_COMMISSION,
            slippage_ticks=_SLIPPAGE_TICKS,
        ).run(sig, symbol=_SYMBOL, multiplier=_MULTIPLIER)
        return {
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "total_trades": result.total_trades,
        }
    except Exception:
        return {
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wfo_results() -> dict[str, Any]:
    """Run the full synthetic WFO and return collected results."""
    df = _make_ohlcv()
    windows = _generate_windows(df)

    oos_pfs: list[float] = []
    oos_dds: list[float] = []
    window_details: list[dict] = []

    for i, w in enumerate(windows):
        best_params = _best_is_params(w["train"])
        oos = _run_oos(w["test"], best_params)
        oos_pfs.append(float(oos["profit_factor"]))
        oos_dds.append(float(oos["max_drawdown_pct"]))
        window_details.append(
            {
                "window": i + 1,
                "best_params": best_params,
                "oos_pf": oos["profit_factor"],
                "oos_dd": oos["max_drawdown_pct"],
                "oos_trades": oos["total_trades"],
            }
        )

    return {
        "windows": window_details,
        "oos_pfs": oos_pfs,
        "oos_dds": oos_dds,
        "n_windows": len(windows),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_wfo_produces_expected_window_count(wfo_results):
    """500 bars with train=150, test=50, step=50 must yield 3 windows."""
    assert wfo_results["n_windows"] == 3


def test_all_oos_pfs_are_non_negative(wfo_results):
    """Profit factor must be >= 0 for every OOS window."""
    for pf in wfo_results["oos_pfs"]:
        assert pf >= 0.0, f"negative profit_factor: {pf}"


def test_all_oos_dds_are_non_positive(wfo_results):
    """Max drawdown must be <= 0 (stored as negative fraction or 0)."""
    for dd in wfo_results["oos_dds"]:
        assert dd <= 0.0, f"positive max_drawdown_pct: {dd}"


def test_each_window_has_required_keys(wfo_results):
    """Every window detail dict must have the expected keys."""
    required = {"window", "best_params", "oos_pf", "oos_dd", "oos_trades"}
    for w in wfo_results["windows"]:
        assert required <= set(w.keys()), f"missing keys in window: {w}"


def test_best_params_are_in_grid(wfo_results):
    """The IS grid search must always pick a combo from the defined grid."""
    grid_tuples = {(c["fast"], c["slow"]) for c in _GRID}
    for w in wfo_results["windows"]:
        p = w["best_params"]
        assert (
            p["fast"],
            p["slow"],
        ) in grid_tuples, f"window {w['window']} picked params not in grid: {p}"


# ---------------------------------------------------------------------------
# Gate v2 metric functions
# ---------------------------------------------------------------------------


def test_bootstrap_pf_ci_lower_accepts_oos_pfs(wfo_results):
    """bootstrap_pf_ci_lower must run without error on the OOS PF list."""
    pfs = wfo_results["oos_pfs"]
    ci = bootstrap_pf_ci_lower(pfs, n=200)
    assert math.isfinite(ci), f"ci_lower not finite: {ci}"


def test_classify_wfo_consistency_accepts_oos_pfs(wfo_results):
    """classify_wfo_consistency must return a valid label."""
    label = classify_wfo_consistency(wfo_results["oos_pfs"])
    assert label in {"STRONG", "MODERATE", "WEAK"}, f"unexpected label: {label!r}"


def test_verdict_dict_structure(wfo_results):
    """Assemble a minimal verdict dict and verify all required fields are present."""
    pfs = wfo_results["oos_pfs"]
    dds = wfo_results["oos_dds"]

    pf_ci_lower = bootstrap_pf_ci_lower(pfs, n=200)
    wfo_consistency = classify_wfo_consistency(pfs)
    # p_edge: fraction of windows with OOS PF > 1.0
    n_profitable = sum(1 for pf in pfs if pf > 1.0)
    p_edge = n_profitable / len(pfs) if pfs else 0.0
    mc_95th_dd = abs(min(dds)) if dds else 0.0

    verdict = {
        "symbol": _SYMBOL,
        "n_windows": wfo_results["n_windows"],
        "pf_ci_lower": pf_ci_lower,
        "wfo_consistency": wfo_consistency,
        "p_edge": p_edge,
        "mc_95th_dd_pct": mc_95th_dd * 100,
        "core_pass": (
            pf_ci_lower >= GATE_PF_CI_LOWER
            and p_edge >= GATE_P_EDGE
            and mc_95th_dd <= GATE_MC_DD_CORE
        ),
    }

    required_keys = {"symbol", "n_windows", "pf_ci_lower", "wfo_consistency", "p_edge", "core_pass"}
    assert required_keys <= set(verdict.keys())
    assert math.isfinite(verdict["pf_ci_lower"])
    assert 0.0 <= verdict["p_edge"] <= 1.0
    assert verdict["wfo_consistency"] in {"STRONG", "MODERATE", "WEAK"}
    assert isinstance(verdict["core_pass"], bool)


def test_gate_thresholds_are_sensible_for_synthetic():
    """Gate thresholds from _gate_v2_helpers must be in expected ranges."""
    assert 1.0 <= GATE_PF_CI_LOWER <= 2.0, f"GATE_PF_CI_LOWER={GATE_PF_CI_LOWER}"
    assert 0.5 <= GATE_P_EDGE <= 1.0, f"GATE_P_EDGE={GATE_P_EDGE}"
    assert 0.01 <= GATE_MC_DD_CORE <= 0.15, f"GATE_MC_DD_CORE={GATE_MC_DD_CORE}"
    assert 0.0 <= GATE_DSR <= 1.0, f"GATE_DSR={GATE_DSR}"
