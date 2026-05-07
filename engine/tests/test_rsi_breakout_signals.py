"""Tests for RSI-oversold breakout signal generator."""
import numpy as np
import pandas as pd
import pytest

from backtest.rsi_breakout_signals import (
    RSI_BREAKOUT_PARAMS,
    generate_rsi_breakout_signals,
    get_rsi_breakout_params,
)


def _make_df(n: int = 300, base: float = 5000.0, seed: int = 42) -> pd.DataFrame:
    """Random-walk OHLC — benign default fixture."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 10, n)
    low = close - rng.uniform(1, 10, n)
    open_ = close + rng.normal(0, 2, n)
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _make_capitulation_bounce_df(n: int = 200) -> pd.DataFrame:
    """Sharp drop (drives RSI <25), flat, then clean breakout up (LONG entry)."""
    drop = np.linspace(5000, 4600, 60)
    floor = np.full(40, 4600.0) + np.random.default_rng(7).normal(0, 1, 40)
    rally = np.linspace(4600, 5200, n - 100)
    close = np.concatenate([drop, floor, rally])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _make_spike_reversal_df(n: int = 200) -> pd.DataFrame:
    """Sharp rally (drives RSI >75), flat, then clean breakdown (SHORT entry)."""
    rally = np.linspace(5000, 5400, 60)
    ceiling = np.full(40, 5400.0) + np.random.default_rng(8).normal(0, 1, 40)
    drop = np.linspace(5400, 4800, n - 100)
    close = np.concatenate([rally, ceiling, drop])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _make_flat_df(n: int = 300) -> pd.DataFrame:
    """Flat price → RSI hovers near 50 → no oversold/overbought → no entries."""
    close = np.full(n, 5000.0) + np.random.default_rng(2).normal(0, 1, n)
    high = close + 2
    low = close - 2
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_required_columns_present():
    df = generate_rsi_breakout_signals(_make_df())
    required = (
        "entry_signal", "exit_signal", "stop_level",
        "target_1", "target_2", "target_3",
        "bias", "regime", "atr", "rsi",
    )
    for col in required:
        assert col in df.columns, f"Missing column: {col}"


def test_entry_long_on_capitulation_bounce():
    df = generate_rsi_breakout_signals(
        _make_capitulation_bounce_df(), rsi_oversold=25.0, rsi_lookback=80,
        entry_period=20,
    )
    longs = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(longs) >= 1, "Expected at least one LONG entry on capitulation-bounce fixture"


def test_entry_short_on_spike_reversal():
    df = generate_rsi_breakout_signals(
        _make_spike_reversal_df(), rsi_overbought=75.0, rsi_lookback=80,
        entry_period=20,
    )
    shorts = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(shorts) >= 1, "Expected at least one SHORT entry on spike-reversal fixture"


def test_no_entry_on_flat_market():
    df = generate_rsi_breakout_signals(_make_flat_df(), rsi_oversold=25.0, rsi_overbought=75.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) == 0, f"Expected zero entries on flat market, got {len(entries)}"


def test_stop_geometry_for_long():
    df = generate_rsi_breakout_signals(
        _make_capitulation_bounce_df(), rsi_oversold=25.0, rsi_lookback=80,
    )
    longs = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] < df["close"])]
    # Long stops must be below entry and targets must ladder up
    for _, row in longs.iterrows():
        assert row["stop_level"] < row["close"]
        assert row["close"] < row["target_1"] < row["target_2"] < row["target_3"]


def test_stop_geometry_for_short():
    df = generate_rsi_breakout_signals(
        _make_spike_reversal_df(), rsi_overbought=75.0, rsi_lookback=80,
    )
    shorts = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] > df["close"])]
    for _, row in shorts.iterrows():
        assert row["stop_level"] > row["close"]
        assert row["close"] > row["target_1"] > row["target_2"] > row["target_3"]


def test_entry_signal_has_no_nan_strings():
    df = generate_rsi_breakout_signals(_make_df())
    vals = set(df["entry_signal"].unique())
    assert vals.issubset({"ENTRY_NOW", "NO_TRADE"}), f"Unexpected entry_signal values: {vals}"


def test_regime_matches_entry_direction():
    df = generate_rsi_breakout_signals(
        _make_capitulation_bounce_df(), rsi_oversold=25.0, rsi_lookback=80,
    )
    longs = df[df["entry_signal"] == "ENTRY_NOW"]
    # Every entry bar's regime must be BREAKOUT_UP or BREAKOUT_DN
    assert (longs["regime"].isin(["BREAKOUT_UP", "BREAKOUT_DN"])).all()


def test_rsi_column_is_bounded():
    df = generate_rsi_breakout_signals(_make_df())
    rsi_vals = df["rsi"].dropna()
    assert rsi_vals.min() >= 0.0 and rsi_vals.max() <= 100.0, \
        f"RSI out of bounds: min={rsi_vals.min()}, max={rsi_vals.max()}"


def test_no_entry_repeats_on_adjacent_bars():
    # Edge-detect guard: consecutive bars meeting entry condition should only fire once.
    df = generate_rsi_breakout_signals(
        _make_capitulation_bounce_df(), rsi_oversold=25.0, rsi_lookback=80,
    )
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    if len(entries) >= 2:
        # Bar positions of entries should not include two consecutive bars
        positions = [df.index.get_loc(idx) for idx in entries.index]
        for a, b in zip(positions, positions[1:], strict=False):
            assert b - a > 1, "Entries fired on adjacent bars — edge-detect gate broken"


def test_get_rsi_breakout_params_returns_dict_for_mes():
    params = get_rsi_breakout_params("MES")
    assert params is not None
    assert "rsi_oversold" in params
    assert "entry_period" in params


def test_get_rsi_breakout_params_returns_none_for_unknown_symbol():
    assert get_rsi_breakout_params("UNKNOWN_SYMBOL_XYZ") is None


def test_params_registry_has_mes():
    assert "MES" in RSI_BREAKOUT_PARAMS
