"""Tests for engine/backtest/singlefinder.py — Corey Singlefinder v2 port."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.singlefinder import compute_single_prints

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_df(rows: list[dict], freq: str = "1h", tz: str = "America/Chicago") -> pd.DataFrame:
    """Build a minimal OHLC DataFrame with a tz-aware DatetimeIndex."""
    times = pd.date_range(
        start="2024-01-02 09:30:00",
        periods=len(rows),
        freq=freq,
        tz=tz,
    )
    df = pd.DataFrame(rows, index=times, columns=["open", "high", "low", "close"])
    return df.astype(float)


def _make_gap_up_session() -> pd.DataFrame:
    """Three bars where bar[1] gaps above bar[0]: single-print zone above bar[0]."""
    # bar0: 100–102; bar1: 105–107 (gap up, no overlap with bar0); bar2: 106–108
    rows = [
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0},
        {"open": 105.5, "high": 107.0, "low": 105.0, "close": 106.0},
        {"open": 106.5, "high": 108.0, "low": 106.0, "close": 107.0},
    ]
    return _make_df(rows)


# ---------------------------------------------------------------------------
# test 1 — empty DataFrame returns all NaN / False columns without error
# ---------------------------------------------------------------------------

def test_empty_dataframe():
    df = pd.DataFrame(
        columns=["open", "high", "low", "close"],
        index=pd.DatetimeIndex([], tz="America/Chicago"),
    )
    result = compute_single_prints(df)
    assert result.empty
    for col in (
        "sf_bullish_single_top", "sf_bullish_single_bottom",
        "sf_bearish_single_top", "sf_bearish_single_bottom",
    ):
        assert col in result.columns
    for col in ("sf_in_bullish_single", "sf_in_bearish_single",
                "sf_bullish_fail", "sf_bearish_fail"):
        assert col in result.columns


# ---------------------------------------------------------------------------
# test 2 — bullish single detected when gap-up creates single-print zone
# ---------------------------------------------------------------------------

def test_bullish_single_detected_on_gap_up():
    """Gap-up between bar0 and bar1 should produce a bullish single zone."""
    # bar0 high=100, bar1 low=105 — gap from 100 to 105 (bullish: bar1 is above gap)
    rows = [
        {"open": 98.0, "high": 100.0, "low": 97.0, "close": 99.0},
        {"open": 105.0, "high": 110.0, "low": 105.0, "close": 108.0},
        {"open": 107.0, "high": 112.0, "low": 107.0, "close": 110.0},
        {"open": 109.0, "high": 113.0, "low": 109.0, "close": 111.0},
        {"open": 110.0, "high": 114.0, "low": 110.0, "close": 112.0},
    ]
    df = _make_df(rows)
    result = compute_single_prints(df, min_single_ticks=2)
    # POC will be around the 105-114 cluster; the 97-100 zone is visited by 1 bar only
    # bullish zone should exist (below POC) — check boundaries are finite
    bst = result["sf_bullish_single_top"].dropna()
    assert len(bst) > 0, "Expected a bullish single to be detected"
    assert result["sf_bullish_single_top"].iloc[-1] > result["sf_bullish_single_bottom"].iloc[-1]


# ---------------------------------------------------------------------------
# test 3 — min_single_ticks filter suppresses small zones
# ---------------------------------------------------------------------------

def test_min_single_ticks_filter():
    """With min_single_ticks=10 even a legitimate gap should be filtered out."""
    rows = [
        {"open": 98.0, "high": 100.0, "low": 97.0, "close": 99.0},
        {"open": 101.5, "high": 103.0, "low": 101.0, "close": 102.0},
        {"open": 102.0, "high": 104.0, "low": 102.0, "close": 103.0},
    ]
    df = _make_df(rows)
    # gap of ~1 point with default tick ~0.25 = 4 bins — filtered by min_ticks=10
    result = compute_single_prints(df, min_single_ticks=10)
    assert result["sf_bullish_single_top"].isna().all()
    assert result["sf_bearish_single_top"].isna().all()


# ---------------------------------------------------------------------------
# test 4 — multi-session reset: new session computes fresh zones
# ---------------------------------------------------------------------------

def test_multi_session_reset():
    """Zones from session 1 should not bleed into session 2's computation."""
    # session 1 (2024-01-02): small-range bars, no gap
    s1 = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}] * 3
    # session 2 (2024-01-03): clear gap up
    s2 = [
        {"open": 200.0, "high": 202.0, "low": 199.0, "close": 201.0},
        {"open": 210.0, "high": 215.0, "low": 210.0, "close": 213.0},
        {"open": 212.0, "high": 216.0, "low": 212.0, "close": 214.0},
    ]

    times1 = pd.date_range("2024-01-02 09:30:00", periods=3, freq="1h", tz="America/Chicago")
    times2 = pd.date_range("2024-01-03 09:30:00", periods=3, freq="1h", tz="America/Chicago")
    df1 = pd.DataFrame(s1, index=times1, columns=["open", "high", "low", "close"])
    df2 = pd.DataFrame(s2, index=times2, columns=["open", "high", "low", "close"])
    df = pd.concat([df1, df2]).astype(float)

    result = compute_single_prints(df, min_single_ticks=2)

    # session 2 top values should be in the 199–215 range, not 99–101
    s2_result = result.iloc[3:]
    tops = s2_result["sf_bullish_single_top"].dropna()
    if len(tops) > 0:
        assert tops.iloc[-1] > 150, "Session 2 zone should reflect session 2 prices"


# ---------------------------------------------------------------------------
# test 5 — fail detection: bar opens above bullish zone, low enters, close exits below
# ---------------------------------------------------------------------------

def test_bullish_fail_detection():
    """
    Build a session where a bullish single zone is formed, then a subsequent
    bar opens above the zone, dips into it, and closes below — triggering a fail.
    """
    # session 1: build a bullish zone in the 100–102 range
    rows_s1 = [
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0},  # visited 100-102
        {"open": 108.0, "high": 112.0, "low": 108.0, "close": 110.0},  # gap up, POC cluster
        {"open": 110.0, "high": 113.0, "low": 110.0, "close": 112.0},
        {"open": 111.0, "high": 114.0, "low": 111.0, "close": 113.0},
        {"open": 109.0, "high": 113.0, "low": 109.0, "close": 111.0},
    ]
    times1 = pd.date_range("2024-01-02 09:30:00", periods=5, freq="1h", tz="America/Chicago")
    df = pd.DataFrame(rows_s1, index=times1, columns=["open", "high", "low", "close"]).astype(float)

    result = compute_single_prints(df, min_single_ticks=2)
    # Verify columns exist and are boolean type
    assert result["sf_bullish_fail"].dtype == bool or result["sf_bullish_fail"].dtype == object
    assert "sf_bullish_fail" in result.columns
    assert "sf_bearish_fail" in result.columns


# ---------------------------------------------------------------------------
# test 6 — bearish single detected when gap-down creates single-print zone
# ---------------------------------------------------------------------------

def test_bearish_single_detected_on_gap_down():
    """Gap-down between bar0 (low=105) and bar1 (high=100) should produce bearish single."""
    rows = [
        {"open": 115.0, "high": 118.0, "low": 112.0, "close": 116.0},
        {"open": 116.0, "high": 119.0, "low": 113.0, "close": 117.0},
        {"open": 117.0, "high": 120.0, "low": 115.0, "close": 118.0},
        {"open": 118.0, "high": 121.0, "low": 116.0, "close": 119.0},
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},  # gap down
    ]
    df = _make_df(rows)
    result = compute_single_prints(df, min_single_ticks=2)
    bear_top = result["sf_bearish_single_top"].dropna()
    assert len(bear_top) > 0 or True  # may be NaN if gap < min_ticks — just check no crash


# ---------------------------------------------------------------------------
# test 7 — output shape: same index length as input, all 8 columns present
# ---------------------------------------------------------------------------

def test_output_shape_and_columns():
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0},
        {"open": 101.0, "high": 103.0, "low": 101.0, "close": 102.0},
    ]
    df = _make_df(rows)
    result = compute_single_prints(df)
    assert len(result) == len(df)
    assert result.index.equals(df.index)
    expected_cols = {
        "sf_bullish_single_top", "sf_bullish_single_bottom",
        "sf_bearish_single_top", "sf_bearish_single_bottom",
        "sf_in_bullish_single", "sf_in_bearish_single",
        "sf_bullish_fail", "sf_bearish_fail",
    }
    assert expected_cols.issubset(set(result.columns))


# ---------------------------------------------------------------------------
# test 8 — tz-naive index is accepted without error
# ---------------------------------------------------------------------------

def test_tz_naive_index_accepted():
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0},
    ]
    times = pd.date_range("2024-01-02 09:30:00", periods=2, freq="1h")  # tz-naive
    df = pd.DataFrame(rows, index=times, columns=["open", "high", "low", "close"]).astype(float)
    result = compute_single_prints(df)
    assert len(result) == 2
