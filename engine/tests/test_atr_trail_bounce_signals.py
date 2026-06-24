"""Tests for the ATR trailing-stop bounce signal (Matt's /ES bounce hypothesis).

Synthetic, deterministic OHLC. No market data required — verifies the logic and
the point-in-time (no look-ahead) invariant, per .claude/rules/testing.md.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.atr_trail_bounce_signals import (
    generate_atr_trail_bounce_signals,
    generate_atr_trail_confluence_signals,
    generate_atr_trail_flip_signals,
)
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


def test_flip_fires_on_state_change():
    # Uptrend then sharp breakdown -> a +1 -> -1 flip -> short entry on the
    # flip bar; reversal back up -> -1 -> +1 flip -> long entry.
    closes = np.concatenate([
        np.linspace(100, 130, 30),  # long state established
        np.linspace(129, 95, 25),   # breakdown -> flip short
        np.linspace(96, 125, 25),   # recovery -> flip long
    ])
    df = _ohlc(closes)
    out = generate_atr_trail_flip_signals(df, factor=3.5)
    entries = out[out["entry_signal"] == "ENTRY_NOW"]
    assert not entries.empty
    # at least one short (target_1 < close) and one long (target_1 > close)
    assert (entries["target_1"] < entries["close"]).any()
    assert (entries["target_1"] > entries["close"]).any()


def test_flip_entry_aligns_with_state_change():
    closes = np.concatenate([np.linspace(100, 130, 30), np.linspace(129, 95, 25)])
    df = _ohlc(closes)
    out = generate_atr_trail_flip_signals(df, factor=3.5)
    state = out["trail_state"]
    for i in out.index[out["entry_signal"] == "ENTRY_NOW"]:
        pos = out.index.get_loc(i)
        if pos == 0:
            continue
        assert state.iloc[pos] != state.iloc[pos - 1], "flip entry without a state change"


def test_flip_no_lookahead_truncation_invariance():
    closes = list(np.linspace(100, 130, 30)) + list(np.linspace(129, 100, 20))
    df = _ohlc(closes)
    full = generate_atr_trail_flip_signals(df, factor=3.5)
    cutoff = 40
    trunc = generate_atr_trail_flip_signals(df.iloc[: cutoff + 1].copy(), factor=3.5)
    for i in range(cutoff + 1):
        assert full.loc[i, "entry_signal"] == trunc.loc[i, "entry_signal"], (
            f"flip bar {i} changed when future bars dropped — look-ahead leak"
        )


def _ohlc_dt(closes, highs=None, lows=None):
    """OHLC with an hourly DatetimeIndex (confluence needs it for sessions)."""
    df = _ohlc(closes, highs, lows)
    df.index = pd.date_range("2025-01-02 08:00", periods=len(df), freq="h", tz="UTC")
    return df


def test_confluence_is_subset_of_base():
    # Confluence trades must be a strict subset of the base flip trades —
    # the gate can only remove entries, never add them. This is what keeps
    # attribution clean (we can see exactly what the VA gate costs/adds).
    closes = np.concatenate([
        np.linspace(100, 130, 40), np.linspace(129, 95, 30), np.linspace(96, 125, 30),
    ])
    df = _ohlc_dt(closes)
    base = generate_atr_trail_flip_signals(df, factor=3.5)
    conf = generate_atr_trail_confluence_signals(df, factor=3.5, base="flip")
    base_entries = set(np.where(base["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    conf_entries = set(np.where(conf["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    assert conf_entries.issubset(base_entries), "confluence added entries not in base"


def test_confluence_strict_drops_more_than_loose():
    closes = np.concatenate([
        np.linspace(100, 130, 40), np.linspace(129, 95, 30), np.linspace(96, 125, 30),
    ])
    df = _ohlc_dt(closes)
    loose = generate_atr_trail_confluence_signals(df, factor=3.5, strict_confluence=False)
    strict = generate_atr_trail_confluence_signals(df, factor=3.5, strict_confluence=True)
    n_loose = int((loose["entry_signal"] == "ENTRY_NOW").sum())
    n_strict = int((strict["entry_signal"] == "ENTRY_NOW").sum())
    assert n_strict <= n_loose, "strict confluence should never keep more trades than loose"


def test_confluence_no_lookahead_truncation_invariance():
    closes = list(np.linspace(100, 130, 40)) + list(np.linspace(129, 100, 30))
    df = _ohlc_dt(closes)
    full = generate_atr_trail_confluence_signals(df, factor=3.5)
    cutoff = 55
    trunc = generate_atr_trail_confluence_signals(df.iloc[: cutoff + 1].copy(), factor=3.5)
    for i in range(cutoff + 1):
        assert full["entry_signal"].iloc[i] == trunc["entry_signal"].iloc[i], (
            f"confluence bar {i} changed when future bars dropped — look-ahead leak"
        )


def test_output_schema_matches_backtester_contract():
    df = _ohlc(np.linspace(100, 120, 30))
    out = generate_atr_trail_bounce_signals(df)
    for col in ["entry_signal", "exit_signal", "stop_level", "target_1",
                "target_2", "target_3", "atr", "trail", "trail_state"]:
        assert col in out.columns


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
