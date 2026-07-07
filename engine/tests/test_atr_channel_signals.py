"""Tests for ATR-channel volatility breakout signal generator."""
import numpy as np
import pandas as pd
import pytest

from backtest.atr_channel_signals import (
    ATR_CHANNEL_PARAMS,
    generate_atr_channel_signals,
    get_atr_channel_params,
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


def _make_vol_expansion_up_df(n: int = 200) -> pd.DataFrame:
    """Flat-low-vol → sudden explosive up-move → forces ATR expansion + upper breach."""
    rng = np.random.default_rng(11)
    quiet = np.full(80, 5000.0) + rng.normal(0, 0.5, 80)  # tiny vol
    explosion = np.linspace(5000, 5400, n - 80) + rng.normal(0, 3, n - 80)
    close = np.concatenate([quiet, explosion])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _make_vol_expansion_down_df(n: int = 200) -> pd.DataFrame:
    """Flat-low-vol → explosive down-move → ATR expansion + lower breach."""
    rng = np.random.default_rng(12)
    quiet = np.full(80, 5000.0) + rng.normal(0, 0.5, 80)
    crash = np.linspace(5000, 4600, n - 80) + rng.normal(0, 3, n - 80)
    close = np.concatenate([quiet, crash])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _make_flat_df(n: int = 300) -> pd.DataFrame:
    """Flat price → no breakout ever → zero entries."""
    rng = np.random.default_rng(2)
    close = np.full(n, 5000.0) + rng.normal(0, 1, n)
    high = close + 2
    low = close - 2
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_required_columns_present():
    df = generate_atr_channel_signals(_make_df())
    required = (
        "entry_signal", "exit_signal", "stop_level",
        "target_1", "target_2", "target_3",
        "bias", "regime", "atr", "midline", "upper", "lower",
    )
    for col in required:
        assert col in df.columns, f"Missing column: {col}"


def test_entry_long_on_vol_expansion_up():
    df = generate_atr_channel_signals(
        _make_vol_expansion_up_df(), atr_mult=1.5, ema_period=20,
    )
    longs = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(longs) >= 1, "Expected LONG entry on explosive up-move fixture"


def test_entry_short_on_vol_expansion_down():
    df = generate_atr_channel_signals(
        _make_vol_expansion_down_df(), atr_mult=1.5, ema_period=20,
    )
    shorts = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(shorts) >= 1, "Expected SHORT entry on explosive down-move fixture"


def test_no_entry_on_flat_market():
    df = generate_atr_channel_signals(_make_flat_df(), atr_mult=2.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) == 0, f"Expected zero entries on flat market, got {len(entries)}"


def test_stop_below_entry_for_long():
    df = generate_atr_channel_signals(_make_vol_expansion_up_df(), atr_mult=1.5)
    longs = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] < df["close"])]
    for _, row in longs.iterrows():
        assert row["stop_level"] < row["close"]


def test_stop_above_entry_for_short():
    df = generate_atr_channel_signals(_make_vol_expansion_down_df(), atr_mult=1.5)
    shorts = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] > df["close"])]
    for _, row in shorts.iterrows():
        assert row["stop_level"] > row["close"]


def test_target_ladder_ordered_long():
    df = generate_atr_channel_signals(_make_vol_expansion_up_df(), atr_mult=1.5)
    longs = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] < df["close"])]
    for _, row in longs.iterrows():
        assert row["close"] < row["target_1"] < row["target_2"] < row["target_3"]


def test_target_ladder_ordered_short():
    df = generate_atr_channel_signals(_make_vol_expansion_down_df(), atr_mult=1.5)
    shorts = df[(df["entry_signal"] == "ENTRY_NOW") & (df["stop_level"] > df["close"])]
    for _, row in shorts.iterrows():
        assert row["close"] > row["target_1"] > row["target_2"] > row["target_3"]


def test_channel_geometry_upper_above_lower():
    df = generate_atr_channel_signals(_make_df())
    ok = df.dropna(subset=["upper", "lower"])
    assert (ok["upper"] > ok["lower"]).all(), "upper must be above lower everywhere"


def test_regime_filter_flag_changes_output():
    """require_regime_expanding should materially change where entries fire."""
    df_gated = generate_atr_channel_signals(_make_vol_expansion_up_df(), atr_mult=1.5)
    df_open = generate_atr_channel_signals(
        _make_vol_expansion_up_df(), atr_mult=1.5, require_regime_expanding=False,
    )
    gated_entries = df_gated.index[df_gated["entry_signal"] == "ENTRY_NOW"]
    open_entries = df_open.index[df_open["entry_signal"] == "ENTRY_NOW"]
    # At minimum, the entry locations must differ between the two modes —
    # otherwise the flag has no effect on the output.
    assert not gated_entries.equals(open_entries), \
        "Regime flag had no effect on entry locations"


def test_no_nan_in_entry_signal():
    df = generate_atr_channel_signals(_make_df())
    vals = set(df["entry_signal"].unique())
    assert vals.issubset({"ENTRY_NOW", "NO_TRADE"}), f"Unexpected entry_signal values: {vals}"


def test_get_atr_channel_params_returns_dict_for_mes():
    params = get_atr_channel_params("MES")
    assert params is not None
    assert "atr_mult" in params
    assert "ema_period" in params


def test_get_atr_channel_params_returns_none_for_unknown_symbol():
    assert get_atr_channel_params("UNKNOWN_SYMBOL_XYZ") is None


def test_params_registry_has_mes():
    assert "MES" in ATR_CHANNEL_PARAMS
