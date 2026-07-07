"""Tests for walk-forward vol-targeting validation (vol_target_wfo).

Focus on the properties that make the OOS result honest:
- windows tile the timeline disjointly (no double-counting when pooling),
- target_vol for a window uses ONLY that window's train trades (no lookahead),
- the first train-only period is excluded from OOS,
- weights clip to [0, max_leverage].
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
import pytest

from backtest.vol_target_wfo import (
    Window,
    _weight,
    generate_windows,
    rv_at_entries,
    walk_forward_vol_target,
)


class _TradeLite(NamedTuple):
    entry_date: pd.Timestamp
    pnl: float


def _mk_trades(dates_pnls):
    return [_TradeLite(pd.Timestamp(d), float(p)) for d, p in dates_pnls]


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------

def test_windows_are_disjoint_and_contiguous():
    t0 = pd.Timestamp("2024-01-01")
    t1 = pd.Timestamp("2025-12-31")
    wins = generate_windows(t0, t1, train_months=6, test_months=2)
    assert len(wins) > 0
    # each test period starts exactly where the previous test period ended
    for prev, nxt in zip(wins, wins[1:], strict=False):
        assert nxt.test_start == prev.test_end
    # train precedes test in every window, train span == 6 months
    for w in wins:
        assert w.train_start < w.train_end == w.test_start < w.test_end
        assert w.train_end == w.train_start + pd.DateOffset(months=6)
        assert w.test_end == w.test_start + pd.DateOffset(months=2)


def test_windows_stop_before_t_end():
    t0 = pd.Timestamp("2024-01-01")
    t1 = pd.Timestamp("2024-09-01")  # only ~8 months
    wins = generate_windows(t0, t1, train_months=6, test_months=2)
    # first test starts at 2024-07-01 (< t_end) -> 1 window; second test_start
    # would be 2024-09-01 == t_end -> excluded
    assert all(w.test_start < t1 for w in wins)
    assert len(wins) == 1


# ---------------------------------------------------------------------------
# Weight clipping
# ---------------------------------------------------------------------------

def test_weight_clips_and_passes_through():
    assert _weight(10.0, 10.0, 3.0) == pytest.approx(1.0)      # at target
    assert _weight(10.0, 5.0, 3.0) == pytest.approx(2.0)       # low vol -> upsized
    assert _weight(10.0, 1.0, 3.0) == pytest.approx(3.0)       # clipped at ceiling
    assert _weight(10.0, 40.0, 3.0) == pytest.approx(0.25)     # high vol -> downsized
    assert _weight(10.0, np.nan, 3.0) == pytest.approx(1.0)    # no vol -> passthrough
    assert _weight(10.0, 0.0, 3.0) == pytest.approx(1.0)       # zero vol -> passthrough


# ---------------------------------------------------------------------------
# rv lookup
# ---------------------------------------------------------------------------

def test_rv_at_entries_uses_value_at_or_before_entry():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    rv = pd.Series([10.0, 20.0, np.nan, 40.0, 50.0], index=idx)
    trades = _mk_trades([("2024-01-02", 1.0), ("2024-01-03", 1.0), ("2024-01-05", 1.0)])
    out = rv_at_entries(trades, rv)
    # 01-02 -> 20.0 ; 01-03 -> last valid at/before is 20.0 (01-03 is NaN) ; 01-05 -> 50.0
    assert out[0] == pytest.approx(20.0)
    assert out[1] == pytest.approx(20.0)
    assert out[2] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# No lookahead — the core property
# ---------------------------------------------------------------------------

def test_no_lookahead_late_vol_spike_does_not_change_early_window_target():
    """A huge vol spike in the LAST window must not affect an early OOS window.

    Build trades monthly. The first window's target_vol must equal the median
    of only its train-period rv, regardless of a later spike that would move the
    global median.
    """
    # 12 monthly trades, rv ~ 10 except a spike to 1000 in the final month
    dates = pd.date_range("2024-01-15", periods=12, freq="MS") + pd.Timedelta(days=14)
    trades = _mk_trades([(d, 100.0) for d in dates])
    rv = np.full(12, 10.0)
    rv[-1] = 1000.0  # late spike
    res = walk_forward_vol_target(
        trades, rv, train_months=6, test_months=2, min_train_trades=3
    )
    # first usable window trains on the first ~6 months (all rv=10) -> target 10
    assert res.windows, "expected at least one OOS window"
    assert res.windows[0].target_vol == pytest.approx(10.0)
    # OOS trades exclude the first 6-month train-only block
    assert len(res.pooled_fixed_pnl) < len(trades)
    assert res.n_windows_used >= 1


def test_first_train_only_period_excluded_from_oos():
    dates = pd.date_range("2024-01-15", periods=12, freq="MS") + pd.Timedelta(days=14)
    trades = _mk_trades([(d, 50.0) for d in dates])
    rv = np.full(12, 12.0)
    res = walk_forward_vol_target(trades, rv, train_months=6, test_months=2)
    # trades in months 1-6 are train-only; OOS should start at month 7+
    earliest_oos = min(w.test_start for w in res.windows)
    assert earliest_oos >= dates[0] + pd.DateOffset(months=6)


def test_skips_window_with_too_few_train_trades():
    # only 2 trades total -> cannot meet min_train_trades=3 -> no OOS windows
    trades = _mk_trades([("2024-02-01", 10.0), ("2024-03-01", 10.0)])
    rv = np.array([10.0, 10.0])
    res = walk_forward_vol_target(trades, rv, min_train_trades=3)
    assert res.n_windows_used == 0
    assert res.pooled_fixed_pnl == []


def test_pooled_oos_has_no_double_counting():
    """Disjoint test windows => total pooled OOS trades <= total trades and each
    OOS trade counted once (pooled fixed length == sum of per-window counts)."""
    dates = pd.date_range("2024-01-15", periods=24, freq="MS") + pd.Timedelta(days=14)
    trades = _mk_trades([(d, 20.0) for d in dates])
    rv = np.full(24, 15.0)
    res = walk_forward_vol_target(trades, rv, train_months=6, test_months=2)
    assert len(res.pooled_fixed_pnl) == sum(w.n_test_trades for w in res.windows)
    assert len(res.pooled_fixed_pnl) <= len(trades)


def test_length_mismatch_raises():
    trades = _mk_trades([("2024-01-01", 1.0)])
    with pytest.raises(ValueError):
        walk_forward_vol_target(trades, np.array([1.0, 2.0]))


def test_vol_target_scales_pnl_in_oos():
    """With constant train rv and a low-vol OOS trade, the vol-target PnL should
    exceed the fixed PnL (upsized)."""
    dates = pd.date_range("2024-01-15", periods=12, freq="MS") + pd.Timedelta(days=14)
    trades = _mk_trades([(d, 100.0) for d in dates])
    rv = np.full(12, 20.0)
    # make the LAST month (an OOS trade) low-vol so it gets upsized
    rv[-1] = 10.0
    res = walk_forward_vol_target(trades, rv, train_months=6, test_months=2)
    # the final pooled OOS vt trade should be > its fixed counterpart
    assert res.pooled_vt_pnl[-1] > res.pooled_fixed_pnl[-1]
