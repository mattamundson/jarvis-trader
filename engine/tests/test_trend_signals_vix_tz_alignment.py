"""Regression tests: tz-alignment for the VIX gate in ``backtest.trend_signals``.

Context (2026-09-17): running the preregistered
``MES_sma_trend_vix_pctile_blockCrisis_v1`` walk-forward runner
(``backtest/run_mes_trend_vix_pctile_rank1.py``) produced **no OOS results and no
verdict**. Every one of the 82 windows aborted with::

    [WARN] IS error block=none: Cannot compare dtypes datetime64[s] and datetime64[us, UTC]

Root cause: ``MES_2019-05-05_2026-08-26_1h.csv`` stores timestamps with a ``+00:00``
offset, so the bar index is tz-aware (``datetime64[us, UTC]`` under pandas 3), while
the daily VIX index built from yfinance is tz-naive (``datetime64[s]``). pandas >= 3.0
raises on a mixed-tz comparison instead of silently comparing unequal, so
``vix_daily.reindex(bar_dates, method="ffill")`` raised inside every window.

These tests pin the fix (``_daily_date_index``) and prove it is semantically inert:
tz-aware and tz-naive bar indexes must yield an identical ``vix_level`` series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.trend_signals import _daily_date_index, generate_sma_trend_signals

FAST = 10
SLOW = 30


def _bars(n: int = 400, tz: str | None = "UTC") -> pd.DataFrame:
    """V-shaped 1h price path so SMA(fast) crosses above SMA(slow) mid-sample."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz=tz)
    steps = np.concatenate([np.linspace(0.0, -40.0, n // 2), np.linspace(-40.0, 40.0, n - n // 2)])
    close = pd.Series(100.0 + steps, index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        },
        index=idx,
    )


def _vix(days: int, increasing: bool) -> pd.DataFrame:
    """Daily VIX frame, tz-naive (as produced by yfinance + normalize())."""
    idx = pd.date_range("2024-01-01", periods=days, freq="D")
    values = np.linspace(12.0, 30.0, days) if increasing else np.linspace(30.0, 12.0, days)
    return pd.DataFrame({"close": values}, index=idx)


def test_daily_date_index_drops_tz_to_naive_midnight():
    aware = pd.date_range("2024-03-01", periods=3, freq="7h", tz="UTC")
    out = _daily_date_index(aware)
    assert out.tz is None
    assert (out == out.normalize()).all()
    assert str(out[0]) == "2024-03-01 00:00:00"


def test_daily_date_index_leaves_naive_index_unchanged():
    naive = pd.date_range("2024-03-01", periods=3, freq="7h")
    out = _daily_date_index(naive)
    assert out.tz is None
    assert list(out) == list(naive.normalize())


def test_daily_date_index_converts_non_utc_zones_to_utc_date():
    """A 02:00 US/Eastern bar is 07:00 UTC the SAME day -> same UTC date."""
    idx = pd.DatetimeIndex([pd.Timestamp("2024-03-01 02:00", tz="US/Eastern")])
    assert str(_daily_date_index(idx)[0]) == "2024-03-01 00:00:00"


def test_tz_aware_bars_with_naive_vix_do_not_raise():
    """The exact regression: mixed-tz reindex used to raise TypeError."""
    out = generate_sma_trend_signals(
        _bars(tz="UTC"), fast=FAST, slow=SLOW, vix_df=_vix(60, increasing=False)
    )
    assert "vix_level" in out.columns
    assert out["vix_level"].notna().any(), "VIX never populated onto the bar index"


def test_tz_aware_and_naive_bars_yield_identical_vix_level():
    """The fix must be semantically inert: same dates -> same VIX values."""
    aware = generate_sma_trend_signals(
        _bars(tz="UTC"), fast=FAST, slow=SLOW, vix_df=_vix(60, increasing=True)
    )
    naive = generate_sma_trend_signals(
        _bars(tz=None), fast=FAST, slow=SLOW, vix_df=_vix(60, increasing=True)
    )
    a = aware["vix_level"].to_numpy(dtype=float)
    n = naive["vix_level"].to_numpy(dtype=float)
    assert np.array_equal(a, n, equal_nan=True)


def test_same_day_vix_close_is_ffilled_onto_that_utc_date():
    """Point-in-time check: a bar on date D sees date D's VIX close (unchanged rule)."""
    vix_df = _vix(60, increasing=False)
    bars = _bars(tz="UTC")
    out = generate_sma_trend_signals(bars, fast=FAST, slow=SLOW, vix_df=vix_df)
    d = bars.index[5].date()
    expected = float(vix_df.loc[pd.Timestamp(d), "close"])
    assert float(out["vix_level"].iloc[5]) == pytest.approx(expected)


def test_crisis_block_suppresses_entries_on_tz_aware_bars():
    """Increasing VIX => trailing percentile ~99.5 (Crisis) at every bar."""
    bars = _bars(tz="UTC")
    vix_df = _vix(60, increasing=True)
    blocked = generate_sma_trend_signals(
        bars, fast=FAST, slow=SLOW, vix_df=vix_df,
        vix_regime_block=("Crisis",), vix_regime_lookback=20,
    )
    assert (blocked["entry_signal"] == "ENTRY_NOW").sum() == 0


def test_tier_series_is_populated_not_all_nan():
    """Discriminating control: blocking the OTHER tiers must still allow entries.

    If the tier series were silently all-NaN the gate would suppress everything,
    which is indistinguishable from a correct Crisis block. An increasing VIX is
    Crisis everywhere, so blocking HighVol/MidVol/LowVol must leave entries intact.
    """
    bars = _bars(tz="UTC")
    vix_df = _vix(60, increasing=True)
    allowed = generate_sma_trend_signals(
        bars, fast=FAST, slow=SLOW, vix_df=vix_df,
        vix_regime_block=("HighVol", "MidVol", "LowVol"), vix_regime_lookback=20,
    )
    assert (allowed["entry_signal"] == "ENTRY_NOW").sum() > 0


def test_no_vix_df_is_still_a_no_op():
    out = generate_sma_trend_signals(_bars(tz="UTC"), fast=FAST, slow=SLOW)
    assert out["vix_level"].isna().all()
