"""Tests for backtest.free_daily_export -- free deep daily OHLCV ingestion.

Covers the module's pure logic: the cache-filename contract (reused from
export_ibkr_history, the single source of truth), normalization of the two free
source shapes (yfinance MultiIndex / Date-index, Stooq newest-first DatetimeIndex),
and the fetch->normalize->write pipeline with an injected fake fetcher (no network).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import free_daily_export as fde
from backtest.export_ibkr_history import CACHE_FILENAME_CONTRACT


# ---------------------------------------------------------------- cache filename
def test_cache_filename_matches_contract():
    name = fde.cache_filename("SPY", "1993-01-29", "2026-06-24")
    assert name == "SPY_1993-01-29_2026-06-24_1d.csv"
    assert CACHE_FILENAME_CONTRACT.match(name)


def test_cache_filename_rejects_bad_symbol():
    # 5-char symbol violates the 2-4 char contract -> must raise, not silently write.
    with pytest.raises(ValueError):
        fde.cache_filename("TOOLONG", "1993-01-29", "2026-06-24")


# --------------------------------------------------------------- normalization
def _yf_frame():
    """yfinance-style: DatetimeIndex named Date, MultiIndex columns (single ticker)."""
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    df = pd.DataFrame(
        {
            ("Open", "SPY"): [100.0, 101.0, 102.0],
            ("High", "SPY"): [101.0, 102.0, 103.0],
            ("Low", "SPY"): [99.0, 100.0, 101.0],
            ("Close", "SPY"): [100.5, 101.5, 102.5],
            ("Volume", "SPY"): [1000, 1100, 1200],
        },
        index=idx,
    )
    df.index.name = "Date"
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _stooq_frame():
    """Stooq-style: DatetimeIndex, plain columns, NEWEST-FIRST order."""
    idx = pd.to_datetime(["2020-01-06", "2020-01-03", "2020-01-02"])
    return pd.DataFrame(
        {
            "Open": [102.0, 101.0, 100.0],
            "High": [103.0, 102.0, 101.0],
            "Low": [101.0, 100.0, 99.0],
            "Close": [102.5, 101.5, 100.5],
            "Volume": [1200, 1100, 1000],
        },
        index=idx,
    )


def test_normalize_yfinance_multiindex():
    out = fde.normalize_daily(_yf_frame())
    assert list(out.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert out["timestamp"].tolist() == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert out["close"].tolist() == [100.5, 101.5, 102.5]


def test_normalize_stooq_sorts_oldest_first():
    out = fde.normalize_daily(_stooq_frame())
    assert out["timestamp"].tolist() == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert out["close"].iloc[0] == 100.5  # oldest row first after sort


def test_normalize_drops_null_close_and_dupes():
    idx = pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03"])
    raw = pd.DataFrame(
        {
            "Open": [1, 1, 2],
            "High": [1, 1, 2],
            "Low": [1, 1, 2],
            "Close": [10.0, 10.0, np.nan],
            "Volume": [1, 1, 1],
        },
        index=idx,
    )
    out = fde.normalize_daily(raw)
    assert out["timestamp"].tolist() == ["2020-01-02"]  # dupe collapsed, null-close dropped


# --------------------------------------------------------- export pipeline (IO)
def _fake_fetcher(df):
    return [("fake", lambda sym: df)]


def test_export_symbol_writes_canonical_cache(tmp_path):
    res = fde.export_symbol("SPY", cache_dir=tmp_path, fetchers=_fake_fetcher(_yf_frame()))
    assert res["status"] == "OK"
    assert res["source"] == "fake"
    assert res["rows"] == 3
    assert res["file"] == "SPY_2020-01-02_2020-01-06_1d.csv"
    written = tmp_path / res["file"]
    assert written.exists()
    back = pd.read_csv(written)
    assert list(back.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(back) == 3


def test_export_symbol_dry_run_writes_nothing(tmp_path):
    res = fde.export_symbol(
        "SPY", cache_dir=tmp_path, dry_run=True, fetchers=_fake_fetcher(_yf_frame())
    )
    assert res["status"] == "OK"
    assert "path" not in res
    assert list(tmp_path.glob("*.csv")) == []


def test_export_symbol_falls_back_to_second_source(tmp_path):
    def boom(sym):
        raise RuntimeError("primary down")

    fetchers = [("primary", boom), ("backup", lambda sym: _stooq_frame())]
    res = fde.export_symbol("QQQ", cache_dir=tmp_path, fetchers=fetchers)
    assert res["status"] == "OK"
    assert res["source"] == "backup"


def test_export_symbol_no_data(tmp_path):
    fetchers = [("empty", lambda sym: pd.DataFrame())]
    res = fde.export_symbol("XYZ", cache_dir=tmp_path, fetchers=fetchers)
    assert res["status"] == "NO_DATA"
