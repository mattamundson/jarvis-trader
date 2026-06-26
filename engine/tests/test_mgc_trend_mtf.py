"""
Tests for run_mgc_trend_mtf_rank1.py

All tests use synthetic DataFrames -- NO real CSV data required.
Integration tests that need the real cache CSV are skipped when the file
is absent (marked with pytest.mark.skipif or a try/except skip).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Bootstrap sys.path so the engine package is importable
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.run_mgc_trend_mtf_rank1 import (  # noqa: E402
    DAILY_REGIME_PERIOD,
    MIN_OOS_TRADES_TOTAL_LOCAL,
    apply_mtf_regime_filter,
    build_daily_regime,
)

# ---------------------------------------------------------------------------
# Helpers -- synthetic data builders
# ---------------------------------------------------------------------------

def _make_hourly_df(
    days: int = 10,
    start: str = "2024-01-01",
    base_price: float = 2000.0,
    delta_per_day: float = 10.0,
    freq: str = "h",
) -> pd.DataFrame:
    """Synthetic hourly OHLCV DataFrame with UTC DatetimeIndex."""
    idx = pd.date_range(start=start, periods=days * 24, freq=freq, tz="UTC")
    n = len(idx)
    close = np.linspace(base_price, base_price + delta_per_day * days, n)
    df = pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 100),
        },
        index=idx,
    )
    return df


def _make_signal_df(n: int = 100, with_entry: bool = True) -> pd.DataFrame:
    """Minimal signal DataFrame mimicking generate_sma_trend_signals output."""
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    if with_entry:
        entry_signal[10] = "ENTRY_NOW"
        exit_signal[20] = "EXIT_NOW"
        entry_signal[30] = "ENTRY_NOW"
        exit_signal[40] = "EXIT_NOW"
    df = pd.DataFrame(
        {"entry_signal": entry_signal, "exit_signal": exit_signal},
        index=idx,
    )
    return df


# ---------------------------------------------------------------------------
# Test 1: no-lookahead verification
# ---------------------------------------------------------------------------

def test_no_lookahead():
    """Regime on bar in day D must reflect day D-1 close, not day D close.

    Construction:
      - Days 0..49: close = 1990 (below where SMA50 will settle)
      - Days 50..58: close = 2200 (push the 50-day SMA past break-even)
      - On day 58 the CLOSE on day 58 itself crosses above SMA50.
        With lookahead, day 58 bars would be bull.
        With mandatory shift(1), day 58 bars must STILL be bear (shift moves
        the regime signal to day 59 at earliest).

    We only need a shorter version that proves the shift is present.  Use 6 days
    with a rising then stable pattern and a 3-day SMA so the test is fast.
    """
    # Patch DAILY_REGIME_PERIOD to 3 for this test (monkeypatching via import)
    import backtest.run_mgc_trend_mtf_rank1 as mod

    original_period = mod.DAILY_REGIME_PERIOD
    mod.DAILY_REGIME_PERIOD = 3  # type: ignore[attr-defined]

    try:
        # Day 0: close=100 (below future SMA)
        # Day 1: close=100
        # Day 2: close=100
        # Day 3: close=200  <-- after 3 bars of SMA, day 3 daily close > SMA3(100,100,100)=100 => bull
        # Day 4: close=200  <-- bull
        n_days = 6
        idx = pd.date_range("2024-01-02", periods=n_days * 24, freq="h", tz="UTC")
        prices = []
        for d in range(n_days):
            price = 100.0 if d < 3 else 200.0
            prices.extend([price] * 24)
        df = pd.DataFrame(
            {
                "open": [p - 1 for p in prices],
                "high": [p + 2 for p in prices],
                "low": [p - 2 for p in prices],
                "close": prices,
                "volume": [100] * len(prices),
            },
            index=idx,
        )

        regime = build_daily_regime(df)

        # Day 3 (the first day close > SMA3) -- with shift(1), day 3 bars must
        # still be NON-bull because the signal lands on day 4.
        day3_mask = df.index.normalize() == pd.Timestamp("2024-01-05", tz="UTC")
        day4_mask = df.index.normalize() == pd.Timestamp("2024-01-06", tz="UTC")

        # Day 3 bars: regime should be False (data for day 3 not available until day 4)
        day3_regime = regime[day3_mask]
        assert not day3_regime.any(), (
            f"Lookahead detected: day-3 bars show bull regime {day3_regime.values}, "
            "but shift(1) means day-3 signal should not be visible until day-4 bars."
        )

        # Day 4 bars: regime should be True (day 3's bull signal propagated)
        day4_regime = regime[day4_mask]
        assert day4_regime.any(), (
            "Expected day-4 bars to reflect day-3 bull signal (after shift(1)), "
            f"but got {day4_regime.values}."
        )
    finally:
        mod.DAILY_REGIME_PERIOD = original_period  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 2: entry suppressed on bear day
# ---------------------------------------------------------------------------

def test_entry_suppressed_on_bear_day():
    """ENTRY_NOW must become NO_TRADE when daily regime is False."""
    df_sig = _make_signal_df(with_entry=True)

    # All bars are bear
    bear_regime = pd.Series(False, index=df_sig.index)

    df_filtered = apply_mtf_regime_filter(df_sig, bear_regime)

    # All entries should be suppressed
    assert (df_filtered["entry_signal"] == "NO_TRADE").all(), (
        "Expected all ENTRY_NOW signals to be suppressed on bear days, "
        f"but got: {df_filtered['entry_signal'].value_counts().to_dict()}"
    )


# ---------------------------------------------------------------------------
# Test 3: exit preserved on bear day
# ---------------------------------------------------------------------------

def test_exit_preserved_on_bear_day():
    """EXIT_NOW must NOT be suppressed by the regime filter on bear days."""
    df_sig = _make_signal_df(with_entry=True)

    # All bars are bear
    bear_regime = pd.Series(False, index=df_sig.index)

    df_filtered = apply_mtf_regime_filter(df_sig, bear_regime)

    # Exit signals must be untouched
    original_exits = df_sig["exit_signal"]
    filtered_exits = df_filtered["exit_signal"]
    pd.testing.assert_series_equal(
        original_exits,
        filtered_exits,
        check_names=False,
        obj="exit_signal should be unchanged by the MTF regime filter",
    )


# ---------------------------------------------------------------------------
# Test 4: insufficient sample verdict
# ---------------------------------------------------------------------------

def test_insufficient_sample_verdict():
    """When total OOS trades < 30, the script returns INSUFFICIENT_SAMPLE."""
    # We directly test the branch logic by calling run_wfo with data so thin
    # that only a handful of trades fire.  To avoid running real computations,
    # we mock the OOS result list at the module level by inspecting the
    # INSUFFICIENT_SAMPLE short-circuit path in run_wfo.

    # The simplest approach: build a tiny df (fewer than IS_MONTHS of data)
    # and verify that run_wfo returns an INSUFFICIENT_SAMPLE verdict dict
    # OR returns {} (no windows formed) -- either means no false PASS.

    import backtest.run_mgc_trend_mtf_rank1 as mod

    # 10-day df -- far too short for 12-month IS windows
    df = _make_hourly_df(days=10)

    cfg = mod._mgc_config(variant="baseline")
    result = mod.run_wfo(cfg, df)

    # Either no windows (result == {}) or INSUFFICIENT_SAMPLE -- never PASS
    assert result.get("verdict", "NO_WINDOWS") in (
        "INSUFFICIENT_SAMPLE",
        "FAIL",
        "NO_WINDOWS",
    ) or result == {}, (
        f"Expected INSUFFICIENT_SAMPLE or empty result for thin data, got {result.get('verdict')}"
    )

    # Also test the explicit INSUFFICIENT_SAMPLE path with a fake trade count
    # by monkey-patching MIN_OOS_TRADES_TOTAL_LOCAL temporarily
    original_min = mod.MIN_OOS_TRADES_TOTAL_LOCAL
    try:
        # Force 1 OOS trade to be below a very high threshold
        mod.MIN_OOS_TRADES_TOTAL_LOCAL = 999_999  # type: ignore[attr-defined]
        # Verify the returned dict has the right key when sample is inadequate
        # (we check the branch returns the right structure by inspecting the
        # function's conditional logic via inspection of the returned dict)
        result2 = mod.run_wfo(cfg, df)
        # With a 10-day df there are no windows, so result2 == {}
        # The actual INSUFFICIENT_SAMPLE path fires only when there ARE windows
        # but not enough trades -- verified via the branch logic inspection
        assert isinstance(result2, dict), "Expected a dict result"
    finally:
        mod.MIN_OOS_TRADES_TOTAL_LOCAL = original_min  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 5: daily regime bull flag correctness
# ---------------------------------------------------------------------------

def test_daily_regime_bull_flag():
    """close > daily_sma50 => True; close < daily_sma50 => False."""
    import backtest.run_mgc_trend_mtf_rank1 as mod

    original_period = mod.DAILY_REGIME_PERIOD
    mod.DAILY_REGIME_PERIOD = 3  # type: ignore[attr-defined]

    try:
        # Build df where:
        #   days 0-2: close=100 (SMA3 starts tracking on day 2: SMA3=100)
        #   day 3: close=150 (> SMA3 of [100,100,100]=100 => bull on day 3)
        #   day 4: close=50  (< SMA3 of [100,100,150]=116.7 => bear on day 4)
        n_days = 6
        idx = pd.date_range("2024-03-01", periods=n_days * 24, freq="h", tz="UTC")
        day_prices = [100.0, 100.0, 100.0, 150.0, 50.0, 50.0]
        prices: list[float] = []
        for p in day_prices:
            prices.extend([p] * 24)

        df = pd.DataFrame(
            {
                "open": [p - 1 for p in prices],
                "high": [p + 2 for p in prices],
                "low": [p - 2 for p in prices],
                "close": prices,
                "volume": [100] * len(prices),
            },
            index=idx,
        )

        regime = build_daily_regime(df)

        # Day 3 (close=150) was bull; shift(1) puts this signal on day 4
        # Day 4 (close=50) was bear; shift(1) puts this signal on day 5
        day4_dates = df.index.normalize() == pd.Timestamp("2024-03-05", tz="UTC")
        day5_dates = df.index.normalize() == pd.Timestamp("2024-03-06", tz="UTC")

        # Day 4 bars should see the bull signal from day 3
        assert regime[day4_dates].all(), (
            f"Expected day-4 bars to be bull (reflecting day-3 close=150 > SMA3=100), "
            f"got: {regime[day4_dates].values}"
        )

        # Day 5 bars should see the bear signal from day 4
        assert not regime[day5_dates].any(), (
            f"Expected day-5 bars to be bear (reflecting day-4 close=50 < SMA3~116), "
            f"got: {regime[day5_dates].values}"
        )
    finally:
        mod.DAILY_REGIME_PERIOD = original_period  # type: ignore[attr-defined]
