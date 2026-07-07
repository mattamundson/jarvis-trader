"""Tests for ADX-EMA trend signal generator."""
import numpy as np
import pandas as pd
import pytest

from backtest.adx_ema_signals import (
    ADX_EMA_PARAMS,
    generate_adx_ema_signals,
    get_adx_ema_params,
)


def _make_df(n: int = 300, base: float = 5000.0, seed: int = 42) -> pd.DataFrame:
    """Random-walk OHLC with no strong trend — expect few or no entries."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 10, n)
    low = close - rng.uniform(1, 10, n)
    open_ = close + rng.normal(0, 2, n)
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _make_trend_df(n: int = 500) -> pd.DataFrame:
    """Three-phase price: flat → strong uptrend → strong downtrend.

    Phase 1 (150 bars flat): ADX should stay low, no entries.
    Phase 2 (200 bars uptrend): ADX rises above 25 with plus_di > minus_di,
        producing a LONG entry once the trend is established.
    Phase 3 (150 bars downtrend): ADX rises again with minus_di > plus_di,
        producing a SHORT entry after the reversal.
    """
    flat = np.full(150, 5000.0) + np.random.default_rng(1).normal(0, 2, 150)
    up = np.linspace(5000, 6000, 200)
    down = np.linspace(6000, 4800, n - 350)
    close = np.concatenate([flat, up, down])
    high = close + 5
    low = close - 5
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def _make_flat_df(n: int = 300) -> pd.DataFrame:
    """Flat price → ADX stays below threshold → zero entries."""
    close = np.full(n, 5000.0) + np.random.default_rng(2).normal(0, 1, n)
    high = close + 2
    low = close - 2
    idx = pd.date_range("2024-06-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_required_columns_present():
    df = generate_adx_ema_signals(_make_df())
    required = (
        "entry_signal", "exit_signal", "stop_level",
        "target_1", "target_2", "target_3",
        "bias", "regime", "atr", "adx",
    )
    for col in required:
        assert col in df.columns, f"Missing column: {col}"


def test_entry_long_on_strong_uptrend():
    df = generate_adx_ema_signals(
        _make_trend_df(), adx_threshold=20.0, ema_period=13, ema_lookback=3,
    )
    long_entries = df[
        (df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BULL")
    ]
    assert len(long_entries) >= 1, "Expected at least one LONG entry on uptrend phase"


def test_entry_short_on_strong_downtrend():
    df = generate_adx_ema_signals(
        _make_trend_df(), adx_threshold=20.0, ema_period=13, ema_lookback=3,
    )
    short_entries = df[
        (df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BEAR")
    ]
    assert len(short_entries) >= 1, "Expected at least one SHORT entry on downtrend phase"


def test_no_entry_on_flat_market():
    # Flat price → ADX below threshold → zero entries
    df = generate_adx_ema_signals(_make_flat_df(), adx_threshold=25.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) == 0, f"Expected zero entries on flat market, got {len(entries)}"


def test_stop_below_entry_for_long():
    df = generate_adx_ema_signals(_make_trend_df(), adx_threshold=20.0)
    longs = df[(df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BULL")]
    for _idx, row in longs.iterrows():
        assert row["stop_level"] < row["close"], \
            f"Long stop ({row['stop_level']:.2f}) must be below entry ({row['close']:.2f})"


def test_stop_above_entry_for_short():
    df = generate_adx_ema_signals(_make_trend_df(), adx_threshold=20.0)
    shorts = df[(df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BEAR")]
    for _idx, row in shorts.iterrows():
        assert row["stop_level"] > row["close"], \
            f"Short stop ({row['stop_level']:.2f}) must be above entry ({row['close']:.2f})"


def test_target_ladder_ordered_long():
    df = generate_adx_ema_signals(_make_trend_df(), adx_threshold=20.0)
    longs = df[(df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BULL")]
    for _, row in longs.iterrows():
        assert row["close"] < row["target_1"] < row["target_2"] < row["target_3"], \
            "Long targets must be ordered entry < t1 < t2 < t3"


def test_target_ladder_ordered_short():
    df = generate_adx_ema_signals(_make_trend_df(), adx_threshold=20.0)
    shorts = df[(df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BEAR")]
    for _, row in shorts.iterrows():
        assert row["close"] > row["target_1"] > row["target_2"] > row["target_3"], \
            "Short targets must be ordered entry > t1 > t2 > t3"


def test_no_nan_in_entry_signal():
    df = generate_adx_ema_signals(_make_df())
    # entry_signal is object dtype filled with strings — no NaN floats should creep in
    vals = set(df["entry_signal"].unique())
    assert vals.issubset({"ENTRY_NOW", "NO_TRADE"}), f"Unexpected entry_signal values: {vals}"


def test_bias_reflects_strong_trend_only():
    df = generate_adx_ema_signals(
        _make_trend_df(), adx_threshold=25.0, ema_period=13, ema_lookback=3,
    )
    # STRONG_BULL / STRONG_BEAR bars must all have ADX >= 25
    trending = df[df["bias"].isin(["STRONG_BULL", "STRONG_BEAR"])]
    assert (trending["adx"] >= 25.0).all(), "STRONG_BULL/BEAR bars must have ADX >= threshold"


def test_regime_matches_bias():
    df = generate_adx_ema_signals(_make_trend_df(), adx_threshold=20.0)
    # TRENDING_BULL regime exists only where bias is STRONG_BULL
    bull_regime = df[df["regime"] == "TRENDING_BULL"]
    assert (bull_regime["bias"] == "STRONG_BULL").all()
    bear_regime = df[df["regime"] == "TRENDING_BEAR"]
    assert (bear_regime["bias"] == "STRONG_BEAR").all()


def test_get_adx_ema_params_returns_dict_for_mes():
    params = get_adx_ema_params("MES")
    assert params is not None
    assert "adx_threshold" in params
    assert "ema_period" in params
    assert "atr_trail_mult" in params


def test_get_adx_ema_params_returns_none_for_unknown_symbol():
    assert get_adx_ema_params("UNKNOWN_SYMBOL_XYZ") is None


def test_params_registry_has_mes():
    assert "MES" in ADX_EMA_PARAMS
