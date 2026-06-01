"""Tests for engine/backtest/gapfinder.py"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.gapfinder import compute_gaps

TZ = "America/Chicago"

# RTH open for US futures in winter (CST = UTC-6): 09:30 CT = 15:30 UTC
# We use this consistently so tests are unambiguous.
RTH_OPEN_UTC_HOUR = 15
RTH_OPEN_UTC_MIN = 30


def _bar(dt: str, o: float, h: float, lo: float, c: float) -> dict:
    return {
        "datetime": pd.Timestamp(dt, tz="UTC"),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
    }


def _make_df(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars).set_index("datetime")


# ---------------------------------------------------------------------------
# Test 1: gap-up detected — zone boundaries correct
# ---------------------------------------------------------------------------

def test_gap_up_detected():
    bars = [
        # Prior session final bar (some afternoon bar, sets prev_session_close=100)
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # RTH open bar: 09:30 CT (CST) = 15:30 UTC; opens at 102 → gap up [100, 102]
        _bar("2024-01-02 15:30:00+00:00", 102.0, 103.0, 101.5, 102.5),
        _bar("2024-01-02 16:30:00+00:00", 102.5, 103.0, 102.0, 102.8),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, session_start_hour=9, session_start_minute=30, tz=TZ)

    open_bar = result.index[1]
    assert result.loc[open_bar, "gap_up_top"] == pytest.approx(102.0)
    assert result.loc[open_bar, "gap_up_bottom"] == pytest.approx(100.0)
    assert np.isnan(result.loc[open_bar, "gap_down_top"])


# ---------------------------------------------------------------------------
# Test 2: gap-down detected — zone boundaries correct
# ---------------------------------------------------------------------------

def test_gap_down_detected():
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # opens at 98 → gap down [98, 100]
        _bar("2024-01-02 15:30:00+00:00", 98.0, 98.5, 97.0, 97.5),
        _bar("2024-01-02 16:30:00+00:00", 97.5, 98.0, 97.0, 97.8),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    open_bar = result.index[1]
    assert result.loc[open_bar, "gap_down_top"] == pytest.approx(100.0)
    assert result.loc[open_bar, "gap_down_bottom"] == pytest.approx(98.0)
    assert np.isnan(result.loc[open_bar, "gap_up_top"])


# ---------------------------------------------------------------------------
# Test 3: no gap when move is below min_gap_pct
# ---------------------------------------------------------------------------

def test_no_gap_session():
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # open 100.05 → gap = 0.05% < 0.1% threshold
        _bar("2024-01-02 15:30:00+00:00", 100.05, 100.1, 99.9, 100.0),
        _bar("2024-01-02 16:30:00+00:00", 100.0, 100.2, 99.9, 100.1),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    for col in ["gap_up_top", "gap_up_bottom", "gap_down_top", "gap_down_bottom"]:
        assert result[col].isna().all(), f"{col} should be all NaN"


# ---------------------------------------------------------------------------
# Test 4: gap-up zone is filled when price drops to / below the bottom
# ---------------------------------------------------------------------------

def test_gap_up_filled():
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # gap up zone [100, 103]
        _bar("2024-01-02 15:30:00+00:00", 103.0, 105.0, 102.0, 104.0),
        # low=99.5 pierces the bottom of the zone (100) → fill
        _bar("2024-01-02 16:30:00+00:00", 104.0, 106.0, 99.5, 101.0),
        _bar("2024-01-02 17:30:00+00:00", 101.0, 102.0, 100.5, 101.5),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    fill_bar = result.index[2]
    assert bool(result.loc[fill_bar, "gap_up_filled_on_bar"]) is True

    # After fill the zone is gone
    post_fill = result.index[3]
    assert np.isnan(result.loc[post_fill, "gap_up_top"])


# ---------------------------------------------------------------------------
# Test 5: min_gap_pct filter — same gap accepted at lower threshold, rejected at higher
# ---------------------------------------------------------------------------

def test_min_gap_pct_filter():
    # gap = 0.5 / 100 = 0.5%
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        _bar("2024-01-02 15:30:00+00:00", 100.5, 101.0, 100.2, 100.6),
        _bar("2024-01-02 16:30:00+00:00", 100.6, 101.0, 100.4, 100.7),
    ]
    df = _make_df(bars)

    # 1% threshold — gap too small, no zone
    result_no = compute_gaps(df, min_gap_pct=0.01, tz=TZ)
    assert result_no["gap_up_top"].isna().all()

    # 0.1% threshold — gap registers
    result_yes = compute_gaps(df, min_gap_pct=0.001, tz=TZ)
    open_bar = result_yes.index[1]
    assert not np.isnan(result_yes.loc[open_bar, "gap_up_top"])


# ---------------------------------------------------------------------------
# Test 6: multiple sessions — new gap of same type replaces prior unfilled gap
# ---------------------------------------------------------------------------

def test_multiple_sessions_most_recent_gap_tracked():
    bars = [
        # Session 1 prior close
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # Session 1 open: gap_up [100, 103]
        _bar("2024-01-02 15:30:00+00:00", 103.0, 105.0, 102.0, 104.0),
        # Session 1 later bar — gap not filled; close=104 becomes next prev_session_close
        _bar("2024-01-02 22:00:00+00:00", 104.0, 104.5, 103.5, 104.0),
        # Session 2 open: prior_close=104, open=108 → new gap_up [104, 108]
        _bar("2024-01-03 15:30:00+00:00", 108.0, 110.0, 107.0, 109.0),
        _bar("2024-01-03 16:30:00+00:00", 109.0, 110.0, 108.5, 109.0),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    session2_open = result.index[3]
    assert result.loc[session2_open, "gap_up_top"] == pytest.approx(108.0)
    assert result.loc[session2_open, "gap_up_bottom"] == pytest.approx(104.0)


# ---------------------------------------------------------------------------
# Test 7: price_in_gap_up reflects whether close is inside the active zone
# ---------------------------------------------------------------------------

def test_price_in_gap_up():
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # gap_up zone [100, 103]; close=101.5 — inside the zone
        _bar("2024-01-02 15:30:00+00:00", 103.0, 104.0, 101.0, 101.5),
        # close=105 — above zone, not inside
        _bar("2024-01-02 16:30:00+00:00", 101.5, 106.0, 101.0, 105.0),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    open_bar = result.index[1]
    assert bool(result.loc[open_bar, "price_in_gap_up"]) is True

    next_bar = result.index[2]
    assert bool(result.loc[next_bar, "price_in_gap_up"]) is False


# ---------------------------------------------------------------------------
# Test 8: gap-down filled when price rallies to the top of the zone
# ---------------------------------------------------------------------------

def test_gap_down_filled():
    bars = [
        _bar("2024-01-01 22:00:00+00:00", 100.0, 100.0, 100.0, 100.0),
        # gap_down zone [96, 100]
        _bar("2024-01-02 15:30:00+00:00", 96.0, 97.0, 95.0, 96.5),
        # high=101 fills the gap (zone top=100)
        _bar("2024-01-02 16:30:00+00:00", 96.5, 101.0, 96.0, 100.5),
        _bar("2024-01-02 17:30:00+00:00", 100.5, 101.0, 100.0, 100.8),
    ]
    df = _make_df(bars)
    result = compute_gaps(df, min_gap_pct=0.001, tz=TZ)

    fill_bar = result.index[2]
    assert bool(result.loc[fill_bar, "gap_down_filled_on_bar"]) is True

    post_fill = result.index[3]
    assert np.isnan(result.loc[post_fill, "gap_down_top"])
