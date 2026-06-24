"""Tests for backtest.resample_intraday -- the offline 5m->15m aggregator (lever 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.resample_intraday import _out_name, resample_ohlcv


def _five_min(n: int, start: str = "2024-05-01 22:00:00+00:00") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n, freq="5min", tz="UTC")
    # deterministic ramp so OHLC aggregation is checkable
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": idx.astype(str),
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1.0] * n,
        }
    )


def test_resample_aggregates_ohlcv_correctly():
    """Three 5m bars -> one 15m bar: open=first, high=max, low=min, close=last, vol=sum."""
    df = resample_ohlcv(_five_min(3), "15min")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == 100.0  # first
    assert row["close"] == 102.0  # last
    assert row["high"] == 102.5  # max of the three highs
    assert row["low"] == 99.5  # min of the three lows
    assert row["volume"] == 3.0  # sum


def test_resample_bins_every_three_bars():
    """Six 5m bars -> two 15m bars, left-labelled at :00 and :15."""
    df = resample_ohlcv(_five_min(6), "15min")
    assert len(df) == 2
    ts = pd.to_datetime(df["timestamp"])
    assert ts.iloc[0] == pd.Timestamp("2024-05-01 22:00:00+00:00")
    assert ts.iloc[1] == pd.Timestamp("2024-05-01 22:15:00+00:00")
    assert df.iloc[1]["open"] == 103.0  # 4th 5m bar opens the 2nd 15m bar


def test_resample_drops_empty_bins():
    """A session gap (missing 5m bars) must not emit an all-NaN 15m bar."""
    a = _five_min(3, "2024-05-01 22:00:00+00:00")
    b = _five_min(3, "2024-05-02 13:30:00+00:00")  # next session, big gap
    df = resample_ohlcv(pd.concat([a, b], ignore_index=True), "15min")
    assert len(df) == 2  # one bar per session, no empty bins between
    assert df["open"].notna().all()


def test_resample_requires_ohlcv_columns():
    with pytest.raises(ValueError, match="missing columns"):
        resample_ohlcv(
            pd.DataFrame({"timestamp": ["2024-05-01 22:00:00+00:00"], "close": [1.0]}), "15min"
        )


def test_out_name_encodes_symbol_and_span():
    from pathlib import Path

    df = resample_ohlcv(_five_min(6), "15min")
    name = _out_name(Path("MGC_2024-05-01_2026-05-29_5m_cont.csv"), df, "15m")
    assert name.startswith("MGC_2024-05-01_")
    assert name.endswith("_15m_cont.csv")
