"""Tests for the ATR trailing-stop bounce signal (Matt's /ES bounce hypothesis).

Synthetic, deterministic OHLC. No market data required — verifies the logic and
the point-in-time (no look-ahead) invariant, per .claude/rules/testing.md.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.atr_trail_bounce_signals import generate_atr_trail_bounce_signals
from backtest.indicators import atr_trailing_stop


def _ohlc(closes, highs=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    highs = closes + 1.0 if highs is None else np.asarray(highs, dtype=float)
    lows = closes - 1.0 if lows is None else np.asarray(lows, dtype=float)
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes,
         "volume": np.full(len(closes), 1000.0)}
    )


def test_trailing_stop_long_sits_below_price_in_uptrend():
    # Steady uptrend -> trail should be in long state (+1) and below close.
    closes = np.linspace(100, 130, 40)
    df = _ohlc(closes)
    trail, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=5, factor=3.5)
    last = state.last_valid_index()
    assert state.loc[last] == 1.0
    assert trail.loc[last] < df["close"].loc[last]


def test_trailing_stop_flips_to_short_on_breakdown():
    closes = np.concatenate([np.linspace(100, 130, 30), np.linspace(129, 95, 25)])
    df = _ohlc(closes)
    _, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=5, factor=3.5)
    assert state.dropna().iloc[0] == 1.0  # seeded long
    assert state.dropna().iloc[-1] == -1.0  # flipped short after the drop


def test_clean_bounce_fires_long_entry():
    # Uptrend establishes a long trail; one bar wicks down to the line and
    # closes back above it; price then holds above for the hold window.
    closes = list(np.linspace(100, 120, 25))
    # bounce bar: deep wick toward the rising trail, close stays up
    closes += [120.5, 121.5, 122.5, 123.5]
    df = _ohlc(closes)
    # carve a wick on the first appended bar (index 25)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=1, touch_tol_atr=0.5)
    assert (out["entry_signal"] == "ENTRY_NOW").any()
    fire = out.index[out["entry_signal"] == "ENTRY_NOW"][0]
    # stop is the line, below entry price for a long
    assert out.loc[fire, "stop_level"] < out.loc[fire, "close"]
    assert out.loc[fire, "target_1"] > out.loc[fire, "close"]


def test_failed_bounce_does_not_fire():
    # Same tag, but price then collapses through the line within the hold
    # window -> trail flips short -> NO long entry should be recorded at/after.
    closes = list(np.linspace(100, 120, 25)) + [120.5, 108, 100, 95]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=2, touch_tol_atr=0.5)
    # With a 2-bar hold requirement and an immediate flip, the long must not fire.
    longs = out[(out["entry_signal"] == "ENTRY_NOW") & (out["target_1"] > out["close"])]
    assert longs.empty


def test_hold_bars_zero_fires_on_reclaim_bar():
    closes = list(np.linspace(100, 120, 25)) + [120.5, 121.5]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=0, touch_tol_atr=0.5)
    # entry should land exactly on the tag bar when no confirmation is required
    assert out.loc[25, "entry_signal"] == "ENTRY_NOW"


def test_no_lookahead_truncation_invariance():
    # The signal at bar i must not change when future bars are removed.
    closes = list(np.linspace(100, 120, 25)) + [120.5, 121.5, 122.5, 123.5, 124.5]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    full = generate_atr_trail_bounce_signals(df, hold_bars=1, touch_tol_atr=0.5)
    cutoff = 27
    truncated = generate_atr_trail_bounce_signals(
        df.iloc[: cutoff + 1].copy(), hold_bars=1, touch_tol_atr=0.5
    )
    for i in range(cutoff + 1):
        assert full.loc[i, "entry_signal"] == truncated.loc[i, "entry_signal"], (
            f"bar {i} changed when future bars were dropped — look-ahead leak"
        )


def test_output_schema_matches_backtester_contract():
    df = _ohlc(np.linspace(100, 120, 30))
    out = generate_atr_trail_bounce_signals(df)
    for col in ["entry_signal", "exit_signal", "stop_level", "target_1",
                "target_2", "target_3", "atr", "trail", "trail_state"]:
        assert col in out.columns


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
