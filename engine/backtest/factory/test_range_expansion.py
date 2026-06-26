"""Tests for the range-expansion generator (bookmark-sourced idea)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.factory.signal_adapter import FULL_CONTRACT, build_signal_frame
from backtest.range_expansion_signals import generate_range_expansion_signals

REF = "backtest.range_expansion_signals:generate_range_expansion_signals"


def _flat_then_expansion(direction: str, n: int = 60) -> pd.DataFrame:
    """Calm bars (small range) then one big directional expansion bar at the end."""
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    close = np.full(n, 100.0)
    high = close + 0.2
    low = close - 0.2
    # Final bar: range ~8 (>> ATR ~0.4), closing at the extreme.
    if direction == "long":
        low[-1], high[-1], close[-1] = 100.0, 108.0, 107.8  # closes near high
    else:
        low[-1], high[-1], close[-1] = 92.0, 100.0, 92.2  # closes near low
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_emits_full_contract_via_adapter():
    bars = _flat_then_expansion("long")
    out = build_signal_frame(REF, bars, {})
    for col in FULL_CONTRACT:
        assert col in out.columns


def test_long_expansion_fires_bull():
    out = generate_range_expansion_signals(_flat_then_expansion("long"), range_mult=1.5)
    last = out.iloc[-1]
    assert last["entry_signal"] == "ENTRY_NOW"
    assert last["bias"] == "STRONG_BULL"
    assert last["stop_level"] < last["close"]  # long stop below price
    assert last["target_1"] > last["close"]


def test_short_expansion_fires_bear():
    out = generate_range_expansion_signals(_flat_then_expansion("short"), range_mult=1.5)
    last = out.iloc[-1]
    assert last["entry_signal"] == "ENTRY_NOW"
    assert last["bias"] == "STRONG_BEAR"
    assert last["stop_level"] > last["close"]  # short stop above price
    assert last["target_1"] < last["close"]


def test_direction_filter_suppresses_shorts():
    out = generate_range_expansion_signals(
        _flat_then_expansion("short"), range_mult=1.5, signal_direction="long"
    )
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_calm_bars_do_not_fire():
    """No expansion -> no entries (guards against firing on noise)."""
    idx = pd.date_range("2025-01-01", periods=50, freq="h")
    close = 100 + np.zeros(50)
    bars = pd.DataFrame(
        {"open": close, "high": close + 0.2, "low": close - 0.2, "close": close}, index=idx
    )
    out = generate_range_expansion_signals(bars, range_mult=1.5)
    assert (out["entry_signal"] == "NO_TRADE").all()
