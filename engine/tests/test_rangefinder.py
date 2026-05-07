"""Tests for engine/backtest/rangefinder.py — Rangefinder v2 port."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.rangefinder import compute_rangefinder


def _make_df(highs, lows, closes=None, opens=None):
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows, strict=False)]  # noqa: E741  # OHLC convention
    if opens is None:
        opens = closes
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )


def test_empty_dataframe_returns_all_columns():
    empty = pd.DataFrame(columns=["open", "high", "low", "close"])
    result = compute_rangefinder(empty)
    expected_cols = {
        "rf_range_high", "rf_range_low", "rf_range_poc",
        "rf_vah", "rf_val", "rf_control_zone_high", "rf_control_zone_low",
        "rf_in_control_zone", "rf_expansion_up", "rf_expansion_down",
    }
    assert expected_cols.issubset(set(result.columns))
    assert len(result) == 0


def test_upward_expansion_detected():
    # Stable range for 20 bars, then a large upward break on bar 21.
    n = 20
    highs = [100.0] * n + [115.0]
    lows  = [95.0]  * n + [94.0]
    df = _make_df(highs, lows)
    result = compute_rangefinder(df, atr_period=14, expansion_multiple=1.0)
    assert result["rf_expansion_up"].iloc[-1] is np.bool_(True)
    assert result["rf_expansion_down"].iloc[-1] is np.bool_(False)


def test_downward_expansion_detected():
    n = 20
    highs = [100.0] * n + [100.5]
    lows  = [95.0]  * n + [80.0]
    df = _make_df(highs, lows)
    result = compute_rangefinder(df, atr_period=14, expansion_multiple=1.0)
    assert result["rf_expansion_down"].iloc[-1] is np.bool_(True)
    assert result["rf_expansion_up"].iloc[-1] is np.bool_(False)


def test_range_persists_when_price_stays_inside():
    n = 30
    highs = [100.0] * n
    lows  = [95.0]  * n
    df = _make_df(highs, lows)
    result = compute_rangefinder(df, atr_period=14, expansion_multiple=1.5)
    # No expansion events after the first bar.
    assert result["rf_expansion_up"].sum() == 0
    assert result["rf_expansion_down"].sum() == 0
    # Range bounds are constant.
    assert (result["rf_range_high"] == result["rf_range_high"].iloc[0]).all()
    assert (result["rf_range_low"] == result["rf_range_low"].iloc[0]).all()


def test_control_zone_flag_close_inside():
    n = 20
    highs = [100.0] * n
    lows  = [90.0]  * n
    # Range = 10. CZ = [90 + 0.382*10, 90 + 0.618*10] = [93.82, 96.18]
    # Close exactly at midpoint 95 → inside.
    closes = [95.0] * n
    df = _make_df(highs, lows, closes=closes)
    result = compute_rangefinder(df, atr_period=14)
    # Need enough bars for ATR warmup; check bars beyond period.
    assert result["rf_in_control_zone"].iloc[15:].all()


def test_control_zone_flag_close_outside():
    n = 20
    highs = [100.0] * n
    lows  = [90.0]  * n
    # Close at 99 — above CZ high (96.18).
    closes = [99.0] * n
    df = _make_df(highs, lows, closes=closes)
    result = compute_rangefinder(df, atr_period=14)
    assert not result["rf_in_control_zone"].iloc[15:].any()


def test_expansion_resets_poc_vah_val():
    # First 20 bars: range 90–100, POC ≈ 95, VAH ≈ 98.5, VAL ≈ 91.5.
    # Bar 21: expansion up to high=115 → new range resets.
    n = 20
    highs = [100.0] * n + [115.0]
    lows  = [90.0]  * n + [89.0]
    df = _make_df(highs, lows)
    result = compute_rangefinder(df, atr_period=14, expansion_multiple=1.0)

    pre_poc  = result["rf_range_poc"].iloc[n - 1]
    post_poc = result["rf_range_poc"].iloc[n]
    assert pre_poc != post_poc, "POC should change after expansion resets the range."

    pre_vah  = result["rf_vah"].iloc[n - 1]
    post_vah = result["rf_vah"].iloc[n]
    assert pre_vah != post_vah

    pre_val  = result["rf_val"].iloc[n - 1]
    post_val = result["rf_val"].iloc[n]
    assert pre_val != post_val


def test_atr_sensitivity_higher_multiple_suppresses_expansion():
    # Same data as upward expansion test — with a very high multiple, should NOT trigger.
    n = 20
    highs = [100.0] * n + [105.0]
    lows  = [95.0]  * n + [94.0]
    df = _make_df(highs, lows)

    result_sensitive = compute_rangefinder(df, atr_period=14, expansion_multiple=0.1)
    result_insensitive = compute_rangefinder(df, atr_period=14, expansion_multiple=100.0)

    # Low multiple → expansion fires; high multiple → no expansion at bar 21.
    assert result_sensitive["rf_expansion_up"].iloc[-1] is np.bool_(True)
    assert result_insensitive["rf_expansion_up"].iloc[-1] is np.bool_(False)


def test_output_columns_present_on_normal_data():
    n = 30
    highs = [100.0 + i * 0.1 for i in range(n)]
    lows  = [95.0  + i * 0.1 for i in range(n)]
    df = _make_df(highs, lows)
    result = compute_rangefinder(df)
    required = [
        "rf_range_high", "rf_range_low", "rf_range_poc",
        "rf_vah", "rf_val",
        "rf_control_zone_high", "rf_control_zone_low",
        "rf_in_control_zone", "rf_expansion_up", "rf_expansion_down",
    ]
    for col in required:
        assert col in result.columns, f"Missing column: {col}"


def test_vah_val_ordering():
    n = 20
    highs = [100.0] * n
    lows  = [90.0]  * n
    df = _make_df(highs, lows)
    result = compute_rangefinder(df, atr_period=14)
    assert (result["rf_vah"] >= result["rf_val"]).all()
    assert (result["rf_control_zone_high"] >= result["rf_control_zone_low"]).all()
    assert (result["rf_range_high"] >= result["rf_range_low"]).all()
