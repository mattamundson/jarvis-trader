"""Tests for the deterministic morning levels engine (Phase A).

The core math lives in compute_levels_from_bars() — a pure function over OHLC
DataFrames — so it is fully unit-testable without live market data. The async
compute_morning_levels() wrapper (thin get_bars fetch) is not exercised here.
"""

import json

import pandas as pd
import pytest

from analysis.morning_levels import (
    DEFAULT_TARGET_RATIOS,
    MorningLevels,
    compute_levels_from_bars,
    resample_ohlc_to_daily,
)


def _daily(highs, lows, closes, start="2026-06-01"):
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": list(closes),
            "high": list(highs),
            "low": list(lows),
            "close": list(closes),
            "volume": [1000] * n,
        },
        index=idx,
    )


def test_pivot_and_triggers_classic_floor():
    # Prior (last) session H=110 L=90 C=100:
    #   pivot = (110+90+100)/3 = 100
    #   r1 = 2*100 - 90 = 110 ; s1 = 2*100 - 110 = 90
    #   r2 = 100 + (110-90) = 120 ; s2 = 100 - 20 = 80
    df = _daily([105, 110], [95, 90], [100, 100])
    lv = compute_levels_from_bars("ES", df, atr_period=2)
    assert lv.pivot == pytest.approx(100.0)
    assert lv.r1 == pytest.approx(110.0)
    assert lv.s1 == pytest.approx(90.0)
    assert lv.r2 == pytest.approx(120.0)
    assert lv.s2 == pytest.approx(80.0)
    assert lv.prior_close == pytest.approx(100.0)
    assert lv.prior_high == pytest.approx(110.0)
    assert lv.prior_low == pytest.approx(90.0)


def test_atr_fib_targets_straddle_prior_close():
    df = _daily([101, 102, 110], [99, 98, 90], [100, 100, 100])
    lv = compute_levels_from_bars("ES", df, atr_period=2, target_ratios=(1.0,))
    assert lv.atr > 0
    assert len(lv.targets_up) == 1 and len(lv.targets_down) == 1
    # up target above prior close, down target below — symmetric around close
    assert lv.targets_up[0] == pytest.approx(lv.prior_close + lv.atr)
    assert lv.targets_down[0] == pytest.approx(lv.prior_close - lv.atr)


def test_default_target_ratios_used_when_unspecified():
    df = _daily([101, 110], [99, 90], [100, 100])
    lv = compute_levels_from_bars("NQ", df, atr_period=2)
    assert lv.target_ratios == list(DEFAULT_TARGET_RATIOS)
    assert len(lv.targets_up) == len(DEFAULT_TARGET_RATIOS)


def test_overnight_range_from_intraday():
    df = _daily([110], [90], [100])
    idx = pd.date_range("2026-06-02 00:00", periods=4, freq="1h", tz="UTC")
    intr = pd.DataFrame(
        {
            "open": [100, 101, 102, 103],
            "high": [101, 103, 104, 102],
            "low": [99, 100, 101, 100],
            "close": [101, 102, 103, 101],
            "volume": [10] * 4,
        },
        index=idx,
    )
    lv = compute_levels_from_bars("ES", df, intraday_df=intr, atr_period=1)
    assert lv.overnight_high == pytest.approx(104.0)
    assert lv.overnight_low == pytest.approx(99.0)
    assert lv.overnight_range == pytest.approx(5.0)


def test_insufficient_bars_yields_no_targets_not_crash():
    # Single daily bar: Wilder ATR(14) is NaN -> no targets, but pivots still compute.
    df = _daily([100], [100], [100])
    lv = compute_levels_from_bars("MGC", df, atr_period=14)
    assert lv.targets_up == [] and lv.targets_down == []
    assert lv.pivot == pytest.approx(100.0)


def test_to_dict_is_json_serializable():
    df = _daily([105, 110], [95, 90], [100, 100])
    lv = compute_levels_from_bars("ES", df, atr_period=2)
    d = lv.to_dict()
    assert d["symbol"] == "ES"
    json.dumps(d)  # must not raise


def test_empty_dataframe_raises():
    with pytest.raises(ValueError):
        compute_levels_from_bars("ES", pd.DataFrame())


def test_symbol_preserved_and_type():
    df = _daily([105, 110], [95, 90], [100, 100])
    lv = compute_levels_from_bars("MGC", df, atr_period=2)
    assert isinstance(lv, MorningLevels)
    assert lv.symbol == "MGC"


def test_resample_1h_to_daily_aggregates_sessions():
    # Two distinct ET calendar days (3 bars each) -> two daily rows.
    idx = list(pd.date_range("2026-06-23 13:00", periods=3, freq="1h", tz="UTC")) + list(
        pd.date_range("2026-06-24 13:00", periods=3, freq="1h", tz="UTC")
    )
    df = pd.DataFrame(
        {
            "timestamp": idx,
            "open": [10, 11, 12, 20, 21, 22],
            "high": [11, 15, 13, 21, 25, 23],
            "low": [9, 10, 11, 19, 20, 21],
            "close": [11, 12, 12, 21, 22, 22],
            "volume": [1] * 6,
        }
    )
    daily = resample_ohlc_to_daily(df, tz="America/New_York")
    assert len(daily) == 2
    assert daily.iloc[0]["high"] == 15 and daily.iloc[0]["low"] == 9
    assert daily.iloc[0]["open"] == 10 and daily.iloc[0]["close"] == 12
    assert daily.iloc[1]["high"] == 25 and daily.iloc[1]["low"] == 19


def test_resample_empty_returns_empty():
    assert resample_ohlc_to_daily(pd.DataFrame()).empty


def test_resample_then_levels_end_to_end():
    idx = pd.date_range("2026-06-01 13:00", periods=20 * 24, freq="1h", tz="UTC")
    base = pd.Series(range(len(idx))) % 50 + 100
    df = pd.DataFrame(
        {
            "timestamp": idx,
            "open": base.values,
            "high": (base + 2).values,
            "low": (base - 2).values,
            "close": base.values,
            "volume": [1] * len(idx),
        }
    )
    daily = resample_ohlc_to_daily(df)
    lv = compute_levels_from_bars("ES", daily, atr_period=14)
    assert lv.pivot > 0
    assert lv.atr > 0  # enough daily bars for ATR(14)
    assert len(lv.targets_up) == len(DEFAULT_TARGET_RATIOS)
