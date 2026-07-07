"""
Sanity tests for the vol-targeting uplift experiment.

Tests are deliberately fast and dependency-free -- they only import the
pure-math helpers from vol_target_experiment.py, not the backtester or
data files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest  # noqa: F401

# Resolve engine root so imports work regardless of cwd
_ENGINE_ROOT = Path(__file__).parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from backtest.vol_target_experiment import (
    _annualized_sharpe,
    _max_drawdown,
    _profit_factor,
    apply_vol_targeting,
    compute_metrics,
)

# ---------------------------------------------------------------------------
# Minimal Trade stub (mirrors backtest.trade_manager.Trade fields we use)
# ---------------------------------------------------------------------------

class _StubTrade:
    """Minimal stand-in for Trade -- only the fields vol_target_experiment needs."""

    def __init__(self, pnl: float, entry_date):
        self.pnl = pnl
        self.entry_date = entry_date


# ---------------------------------------------------------------------------
# Test 1: weight=1 when rv_at_entry == target_vol reproduces fixed PnL exactly
# ---------------------------------------------------------------------------

def test_weight_one_reproduces_fixed_pnl():
    """When every entry-bar rv equals the target_vol, weight=1 and vt_pnl == fixed_pnl."""
    import pandas as pd

    # Build a tiny price DataFrame with constant log returns so rv is constant
    dates = pd.date_range("2025-01-01", periods=50, freq="1h")
    # All prices the same => log returns = 0 => rv = 0; use artificial series instead
    # We'll inject rv directly via a pd.Series.
    close = pd.Series(np.exp(np.random.default_rng(0).normal(0, 0.01, 50)).cumprod() * 100, index=dates)
    df = pd.DataFrame({"close": close}, index=dates)

    # Inject a constant rv series (e.g. all 10%)
    const_rv = 10.0
    rv_series = pd.Series([const_rv] * 50, index=dates)

    # Three trades with entry at dates[25], [30], [40]
    trades = [
        _StubTrade(pnl=200.0, entry_date=dates[25]),
        _StubTrade(pnl=-100.0, entry_date=dates[30]),
        _StubTrade(pnl=350.0, entry_date=dates[40]),
    ]

    fixed_pnl, vt_pnl, target_vol = apply_vol_targeting(trades, df, rv_series)

    # target_vol = median(rv_at_entries) = median([10, 10, 10]) = 10.0
    assert abs(target_vol - const_rv) < 1e-9, f"target_vol should be {const_rv}, got {target_vol}"

    # weight at every entry = target_vol / rv_at_entry = 10/10 = 1 => identical PnL
    for orig, vt in zip(fixed_pnl, vt_pnl, strict=True):
        assert abs(vt - orig) < 1e-9, f"Expected vt_pnl == fixed_pnl, got {vt} vs {orig}"


# ---------------------------------------------------------------------------
# Test 2: clipping at max_leverage=3 prevents weights above the cap
# ---------------------------------------------------------------------------

def test_clipping_at_max_leverage():
    """When rv_at_entry is very small, weight is clamped to max_leverage=3."""
    import pandas as pd

    dates = pd.date_range("2025-06-01", periods=30, freq="1h")
    df = pd.DataFrame({"close": np.ones(30) * 100}, index=dates)

    # target_vol = 10%, entry rv very small (1%) => raw weight = 10/1 = 10; clamped to 3
    very_low_rv = 1.0
    target_vol_value = 10.0
    rv_series = pd.Series([very_low_rv] * 30, index=dates)

    trades = [
        _StubTrade(pnl=100.0, entry_date=dates[5]),
    ]

    max_lev = 3.0
    fixed_pnl, vt_pnl, target_vol = apply_vol_targeting(trades, df, rv_series, max_leverage=max_lev)

    assert abs(target_vol - very_low_rv) < 1e-9  # all entries same rv => target = same
    # weight = clip(very_low_rv / very_low_rv, 0, 3) = 1 when target==rv
    # so test with a manipulated scenario: directly verify the clip math
    raw_weight = target_vol_value / very_low_rv  # 10.0
    clipped = float(np.clip(raw_weight, 0.0, max_lev))
    assert clipped == max_lev, f"Expected clip to {max_lev}, got {clipped}"

    # Verify apply_vol_targeting clips when target > rv
    rv_series_low = pd.Series([0.5] * 30, index=dates)
    rv_high_target = pd.Series([target_vol_value] * 30, index=dates)
    # target_vol will be 0.5 (median of entry rvs); raw_w = 0.5/0.5 = 1 again
    # To explicitly test clipping we override via a single-trade case:
    # target_vol (=entry rv median) = 10, entry_rv = 1 => w = 10/1 = 10 => clipped to 3
    # Build rv_series that has 10 at mid-point (drives target_vol = 10)
    # and 1 at the entry bar (drives clipping)
    rv_mixed = pd.Series([10.0] * 29 + [1.0], index=dates)
    # Only 1 trade at last bar
    trade_last = [_StubTrade(pnl=500.0, entry_date=dates[29])]
    fixed_2, vt_2, tv_2 = apply_vol_targeting(trade_last, df, rv_mixed, max_leverage=max_lev)

    # target_vol = median([1.0]) = 1.0 (only 1 entry)
    # That's 1 entry, so target_vol = rv_at_entry => w = 1 => no clip triggered
    # To properly trigger clipping: two trades, one at high-rv bar, one at low-rv bar
    dates2 = pd.date_range("2025-06-01", periods=60, freq="1h")
    df2 = pd.DataFrame({"close": np.ones(60) * 100}, index=dates2)
    rv_for_clip = pd.Series(np.where(np.arange(60) < 30, 10.0, 1.0), index=dates2)
    trades2 = [
        _StubTrade(pnl=100.0, entry_date=dates2[15]),  # rv=10
        _StubTrade(pnl=100.0, entry_date=dates2[45]),  # rv=1
    ]
    fixed_3, vt_3, tv_3 = apply_vol_targeting(trades2, df2, rv_for_clip, max_leverage=max_lev)
    # target_vol = median([10, 1]) = 5.5
    # trade[0]: w = clip(5.5/10, 0, 3) = 0.55 => vt_pnl = 55
    # trade[1]: w = clip(5.5/1,  0, 3) = 3.0  => vt_pnl = 300  (CLIPPED)
    assert abs(tv_3 - 5.5) < 1e-9, f"target_vol should be 5.5, got {tv_3}"
    assert abs(vt_3[0] - 55.0) < 1e-9, f"trade[0] vt_pnl should be 55, got {vt_3[0]}"
    assert abs(vt_3[1] - 300.0) < 1e-9, f"trade[1] vt_pnl should be 300 (clipped), got {vt_3[1]}"


# ---------------------------------------------------------------------------
# Additional sanity tests for metric helpers
# ---------------------------------------------------------------------------

def test_profit_factor_basic():
    # gross_profit=175, gross_loss=75 => PF=175/75=7/3
    assert abs(_profit_factor([100.0, -50.0, 75.0, -25.0]) - 7 / 3) < 1e-9
    assert _profit_factor([]) == 0.0
    assert _profit_factor([100.0]) == float("inf")


def test_max_drawdown_basic():
    # PnL: +100, -150, +50 => cumsum [100, -50, 0] => peak [100, 100, 100] => dd [0, 150, 100]
    assert abs(_max_drawdown([100.0, -150.0, 50.0]) - 150.0) < 1e-9
    assert _max_drawdown([]) == 0.0


def test_annualized_sharpe_constant_positive():
    # All trades same => std=0 => sharpe=0
    pnl = [100.0] * 10
    assert _annualized_sharpe(pnl, 365.0) == 0.0


def test_compute_metrics_roundtrip():
    pnl = [200.0, -100.0, 300.0, -50.0]
    m = compute_metrics(pnl, 365.0)
    assert m.n_trades == 4
    assert abs(m.profit_factor - (500 / 150)) < 1e-6
    assert m.max_dd >= 0
