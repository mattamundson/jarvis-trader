"""US-009 tests — Keltner Channels port (backtest/keltner_signals.py).

Faithful port of shared_shared_shared_shared_kelt_3.01STUDY.ts:
  mid   = SMA(price, length)
  shift = factor * SMA(TrueRange, length)
  upper = mid + shift ; lower = mid - shift

Pure indicator; not wired to routing/auto-trade.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.keltner_signals import compute_keltner


def _df(closes, hi=1.0, lo=1.0):
    """OHLC frame: open=close, high=close+hi, low=close-lo."""
    closes = list(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + hi for c in closes],
            "low": [c - lo for c in closes],
            "close": closes,
        }
    )


def test_known_values_constant_increment():
    # close 10,11,12,... high=c+1 low=c-1 → TrueRange == 2 on every bar, so
    # SMA(TR,3)=2 → shift = factor(2)*2 = 4. mid = SMA(close,3).
    df = _df(range(10, 20))
    out = compute_keltner(df, length=3, factor=2.0)
    # bar index 2 is the first fully-warmed bar: mid=(10+11+12)/3=11.
    row = out.iloc[2]
    assert np.isclose(row["kc_mid"], 11.0)
    assert np.isclose(row["kc_upper"], 15.0)   # 11 + 4
    assert np.isclose(row["kc_lower"], 7.0)    # 11 - 4
    assert np.isclose(row["kc_width"], 8.0)
    assert np.isclose(row["kc_pct_b"], (12.0 - 7.0) / 8.0)  # close 12 → 0.625
    assert row["kc_position"] == "inside"


def test_warmup_is_nan_and_none():
    df = _df(range(10, 20))
    out = compute_keltner(df, length=3, factor=2.0)
    assert np.isnan(out.iloc[0]["kc_mid"])
    assert np.isnan(out.iloc[1]["kc_mid"])
    assert out.iloc[0]["kc_position"] is None
    assert out.iloc[1]["kc_position"] is None


def test_position_above_on_upside_break():
    # Flat then a jump; small factor so the band is tight enough to be pierced.
    df = _df([100, 100, 100, 100, 103], hi=0.1, lo=0.1)
    out = compute_keltner(df, length=3, factor=0.5)
    last = out.iloc[-1]
    assert last["kc_position"] == "above"
    assert last["kc_pct_b"] > 1.0  # above the upper band


def test_position_below_on_downside_break():
    df = _df([100, 100, 100, 100, 97], hi=0.1, lo=0.1)
    out = compute_keltner(df, length=3, factor=0.5)
    last = out.iloc[-1]
    assert last["kc_position"] == "below"
    assert last["kc_pct_b"] < 0.0  # below the lower band


def test_band_ordering_invariant():
    rng = [100, 101, 99, 102, 98, 103, 97, 104, 96, 105, 95, 106]
    out = compute_keltner(_df(rng), length=4, factor=3.0)
    warm = out.dropna(subset=["kc_mid", "kc_upper", "kc_lower"])
    assert (warm["kc_lower"] <= warm["kc_mid"]).all()
    assert (warm["kc_mid"] <= warm["kc_upper"]).all()


def test_price_source_changes_midline():
    df = _df(range(10, 20), hi=2.0, lo=1.0)  # asymmetric so ohlc4 != close
    close_out = compute_keltner(df, length=3, price="close")
    ohlc4_out = compute_keltner(df, length=3, price="ohlc4")
    # ohlc4 = (open+high+low+close)/4 with high=c+2, low=c-1 → mean shifted up by 0.25.
    i = 5
    assert not np.isclose(close_out.iloc[i]["kc_mid"], ohlc4_out.iloc[i]["kc_mid"])


def test_invalid_price_raises():
    with pytest.raises(ValueError):
        compute_keltner(_df(range(10, 20)), price="vwap")


def test_empty_and_missing_columns_are_safe():
    empty = compute_keltner(pd.DataFrame(), length=3)
    for col in ("kc_mid", "kc_upper", "kc_lower", "kc_width", "kc_pct_b", "kc_position"):
        assert col in empty.columns
    # Missing OHLC columns → guard returns the columns without raising.
    partial = compute_keltner(pd.DataFrame({"close": [1, 2, 3]}), length=2)
    assert "kc_mid" in partial.columns
    assert partial["kc_position"].isna().all() or (partial["kc_position"] == None).all()  # noqa: E711
