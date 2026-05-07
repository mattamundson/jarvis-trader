"""
Tests for engine/backtest/ib_signals.py
All DataFrames are synthetic — no external data sources hit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.ib_signals import compute_initial_balance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(dates_minutes: list[tuple], tz: str = "America/Chicago") -> pd.DataFrame:
    """
    Build a minimal OHLC DataFrame from a list of
    (date_str, hour, minute, open_, high, low, close) tuples.
    Index is tz-aware at `tz`.
    """
    records = []
    for date_str, hour, minute, open_, high, low, close in dates_minutes:
        ts = pd.Timestamp(f"{date_str} {hour:02d}:{minute:02d}:00", tz=tz)
        records.append({"timestamp": ts, "open": open_, "high": high, "low": low, "close": close})
    df = pd.DataFrame(records).set_index("timestamp")
    return df


# ---------------------------------------------------------------------------
# Test 1 — trivial 1-day happy path
# ---------------------------------------------------------------------------

def test_single_day_ib_computed():
    """IB high/low should equal the rolling max-high/min-low of the 9:30–10:29 bars."""
    bars = []
    # IB window: 9:30, 9:31 — high=105, 110; low=95, 90
    bars.append(("2026-01-05", 9, 30, 100, 105, 95, 102))
    bars.append(("2026-01-05", 9, 31, 102, 110, 90, 108))
    # outside IB window (bar at 10:30)
    bars.append(("2026-01-05", 10, 30, 108, 115, 105, 113))
    df = _make_bars(bars)

    # Default open_minutes=60, so window is [9:30, 10:29] inclusive.
    # Let's use open_minutes=2 to capture only the two bars above.
    result = compute_initial_balance(df, open_minutes=2)

    # IB bars themselves should be NaN for ib_high/ib_low (not yet frozen).
    assert pd.isna(result.loc[result.index[0], "ib_high"])
    assert pd.isna(result.loc[result.index[1], "ib_high"])

    # Post-IB bar should carry frozen IB.
    post = result.iloc[2]
    assert post["ib_high"] == pytest.approx(110.0)
    assert post["ib_low"] == pytest.approx(90.0)
    assert post["ib_mid"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Test 2 — multi-day IB resets each session
# ---------------------------------------------------------------------------

def test_multi_day_ib_resets():
    """Each session must compute its own IB independently."""
    bars = []
    # Day 1 IB: high=110, low=90
    bars.append(("2026-01-05", 9, 30, 100, 110, 90, 105))
    bars.append(("2026-01-05", 10, 30, 105, 112, 92, 110))  # post-IB
    # Day 2 IB: high=200, low=180
    bars.append(("2026-01-06", 9, 30, 190, 200, 180, 195))
    bars.append(("2026-01-06", 10, 30, 195, 205, 182, 200))  # post-IB

    result = compute_initial_balance(_make_bars(bars), open_minutes=1)

    day1_post = result.iloc[1]
    day2_post = result.iloc[3]

    assert day1_post["ib_high"] == pytest.approx(110.0)
    assert day1_post["ib_low"] == pytest.approx(90.0)
    assert day2_post["ib_high"] == pytest.approx(200.0)
    assert day2_post["ib_low"] == pytest.approx(180.0)
    # IB levels must NOT bleed across days.
    assert day2_post["ib_high"] != day1_post["ib_high"]


# ---------------------------------------------------------------------------
# Test 3 — pre-market bars excluded from IB computation
# ---------------------------------------------------------------------------

def test_premarket_bars_excluded_from_ib():
    """
    A bar at 8:00 CT with high=9999 must NOT influence ib_high.
    """
    bars = []
    # Pre-market spike — must not pollute IB.
    bars.append(("2026-01-05", 8, 0, 100, 9999, 50, 100))
    # IB window bar (only one, high=110, low=90).
    bars.append(("2026-01-05", 9, 30, 100, 110, 90, 105))
    # Post-IB bar.
    bars.append(("2026-01-05", 10, 30, 105, 115, 95, 112))

    result = compute_initial_balance(_make_bars(bars), open_minutes=1)

    post = result.iloc[2]
    assert post["ib_high"] == pytest.approx(110.0), (
        f"Expected ib_high=110, got {post['ib_high']}. "
        "Pre-market bar leaked into IB calculation."
    )
    assert post["ib_low"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Test 4 — fresh breakout fires exactly once per session
# ---------------------------------------------------------------------------

def test_fresh_breakout_fires_once():
    """
    ib_high_fresh_breakout must be True on the FIRST close > ib_high, then
    False even if price remains above or dips-and-re-breaks.
    """
    bars = []
    # IB bar: high=110, low=90.
    bars.append(("2026-01-05", 9, 30, 100, 110, 90, 105))
    # Post-IB: close=105 — no breakout.
    bars.append(("2026-01-05", 10, 30, 105, 112, 100, 105))
    # First breakout: close=115.
    bars.append(("2026-01-05", 10, 31, 110, 116, 108, 115))
    # Still above but NOT fresh.
    bars.append(("2026-01-05", 10, 32, 115, 120, 112, 118))
    # Dip below and re-break — still NOT fresh (already fired).
    bars.append(("2026-01-05", 10, 33, 108, 113, 107, 112))
    bars.append(("2026-01-05", 10, 34, 112, 117, 110, 116))

    result = compute_initial_balance(_make_bars(bars), open_minutes=1)

    fresh = result["ib_high_fresh_breakout"].tolist()
    # [IB window bar, no-break, FIRST break, still above, dip, re-break]
    assert not fresh[0]  # IB bar — ib_high is NaN here
    assert not fresh[1]  # close=105 <= 110
    assert fresh[2]   # first cross
    assert not fresh[3]  # already fired
    assert not fresh[4]  # dipped back
    assert not fresh[5]  # re-break — NOT a fresh signal again


# ---------------------------------------------------------------------------
# Test 5 — no breakout all day
# ---------------------------------------------------------------------------

def test_no_breakout_all_day():
    """When price never crosses IB High or Low, both fresh_breakout flags stay False."""
    bars = []
    bars.append(("2026-01-05", 9, 30, 100, 110, 90, 105))  # IB bar
    # Three post-IB bars trapped inside IB range.
    bars.append(("2026-01-05", 10, 30, 105, 109, 93, 100))
    bars.append(("2026-01-05", 11, 0, 100, 108, 92, 101))
    bars.append(("2026-01-05", 12, 0, 101, 107, 91, 99))

    result = compute_initial_balance(_make_bars(bars), open_minutes=1)

    assert result["ib_high_fresh_breakout"].sum() == 0
    assert result["ib_low_fresh_breakout"].sum() == 0
    assert result["above_ib_high"].sum() == 0
    assert result["below_ib_low"].sum() == 0


# ---------------------------------------------------------------------------
# Test 6 — missing DatetimeIndex raises ValueError
# ---------------------------------------------------------------------------

def test_missing_datetime_index_raises():
    """Non-DatetimeIndex must raise ValueError with a clear message."""
    df = pd.DataFrame(
        {"high": [110.0], "low": [90.0], "close": [100.0]},
        index=[0],
    )
    with pytest.raises(ValueError, match="DatetimeIndex"):
        compute_initial_balance(df)


# ---------------------------------------------------------------------------
# Test 7 — 5-min bars: IB window captures correct bars
# ---------------------------------------------------------------------------

def test_5min_bars_ib_window():
    """
    On 5-min bars with open_minutes=60 the IB window = [9:30, 10:25].
    Bar at 10:30 is the first post-IB bar and must carry the frozen IB.
    """
    bars = []
    # 5-min IB bars (9:30 .. 10:25 = 12 bars, 60 min).
    for minute in range(30, 90, 5):  # 30,35,...,85 → 9:30..10:25
        hour = 9 + minute // 60
        m = minute % 60
        bars.append(("2026-01-05", hour, m, 100, 100 + minute * 0.1, 100 - minute * 0.05, 100))
    # Post-IB bar at 10:30.
    bars.append(("2026-01-05", 10, 30, 100, 200, 50, 150))

    result = compute_initial_balance(_make_bars(bars), open_minutes=60)

    post = result.iloc[-1]
    # IB high must be from the window bars (all <= 100+85*0.1 = 108.5), NOT 200.
    assert post["ib_high"] < 110.0
    assert post["ib_low"] > 50.0


# ---------------------------------------------------------------------------
# Test 8 — ib_low_fresh_breakout fires correctly
# ---------------------------------------------------------------------------

def test_ib_low_fresh_breakout_fires_once():
    """Mirror of test 4 but for the downside breakout."""
    bars = []
    bars.append(("2026-01-05", 9, 30, 100, 110, 90, 100))  # IB bar
    bars.append(("2026-01-05", 10, 30, 100, 108, 92, 95))   # inside
    bars.append(("2026-01-05", 10, 31, 95, 97, 85, 88))     # FIRST breakdown
    bars.append(("2026-01-05", 10, 32, 88, 91, 83, 85))     # still below, not fresh
    bars.append(("2026-01-05", 10, 33, 92, 95, 91, 93))     # bounced above IB low
    bars.append(("2026-01-05", 10, 34, 93, 94, 86, 87))     # re-break, not fresh

    result = compute_initial_balance(_make_bars(bars), open_minutes=1)

    fresh = result["ib_low_fresh_breakout"].tolist()
    assert not fresh[0]
    assert not fresh[1]
    assert fresh[2]
    assert not fresh[3]
    assert not fresh[4]
    assert not fresh[5]
