"""
JARVIS TRADER — Databento loader cache-hit regression tests
===========================================================
Covers engine/backtest/databento_loader.py `_find_cache()` / `fetch_ohlcv()`
cache path. Regression for the tz-aware vs tz-naive compare bug (2026-08-18):

`_write_cache` persists a UTC DatetimeIndex via `df.reset_index()`, so cache
CSVs round-trip tz-aware (`+00:00`). `_find_cache` used to compare against
`pd.Timestamp(start)` (naive), which raised TypeError — swallowed by
`except Exception: continue` — so deep 2015-* caches NEVER matched and every
deep fetch re-downloaded from Databento.

These tests never touch the network: they write a cache file into a temp dir,
point CACHE_DIR there, and assert fetch_ohlcv returns the cached frame without
importing/calling the databento client.
"""

from __future__ import annotations

import sys
from types import ModuleType

import pandas as pd
import pytest

from backtest import databento_loader as dl


def _block_network(monkeypatch) -> None:
    """Make the databento client import fail loudly if the loader ever tries it.

    The cache-hit path returns before `import databento`, so any test that
    reaches this module and still passes proves no network call was made.
    """
    fake = ModuleType("databento")

    class Historical:  # pragma: no cover - must never be constructed
        def __init__(self, *args, **kwargs):
            raise AssertionError("databento client constructed — network path taken!")

    fake.Historical = Historical
    monkeypatch.setitem(sys.modules, "databento", fake)


def _write_tz_aware_cache(tmp_path, filename: str, start: str, end: str) -> None:
    """Write a cache CSV exactly the way _write_cache does (tz-aware UTC index).

    Sparse (a handful of rows spanning the range) on purpose: _find_cache only
    inspects ts.min()/ts.max(), so a dense 100k-row file just slows the test
    (and the host is RAM-starved; the real deep caches are 40k rows).
    """
    idx = pd.to_datetime([start, "2017-06-01", "2020-01-01", "2023-01-01", end], utc=True)
    idx.name = "timestamp"  # _write_cache resets a set_index("timestamp") frame
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10,
        },
        index=idx,
    )
    out = df.reset_index()
    out.to_csv(tmp_path / filename, index=False)


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    """Point CACHE_DIR at a temp dir so tests never touch real caches."""
    monkeypatch.setattr(dl, "CACHE_DIR", tmp_path)
    return tmp_path


class TestFindCacheTzAware:
    def test_deep_tz_aware_cache_hits(self, tmp_path):
        """The exact bug: tz-aware deep cache must match a later start range."""
        _write_tz_aware_cache(
            tmp_path, "MGC_2015-01-01_2026-08-04_1h.csv", "2015-01-01", "2026-08-04"
        )
        hit = dl._find_cache("MGC", "2024-01-01", "2026-08-04", "1h")
        assert hit is not None
        assert hit.name == "MGC_2015-01-01_2026-08-04_1h.csv"

    def test_missing_range_returns_none(self, tmp_path):
        """Cache that starts after the requested start must NOT match."""
        _write_tz_aware_cache(
            tmp_path, "MGC_2019-01-01_2026-08-04_1h.csv", "2019-01-01", "2026-08-04"
        )
        hit = dl._find_cache("MGC", "2015-01-01", "2026-08-04", "1h")
        assert hit is None

    def test_naive_cache_also_matches(self, tmp_path):
        """Polygon-style naive timestamps still match (localized to UTC)."""
        filename = "MGC_2015-01-01_2026-08-04_1h.csv"
        idx = pd.to_datetime(
            ["2015-01-01", "2017-06-01", "2020-01-01", "2023-01-01", "2026-08-04"]
        )  # naive
        idx.name = "timestamp"
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10},
            index=idx,
        )
        df.reset_index().to_csv(tmp_path / filename, index=False)
        hit = dl._find_cache("MGC", "2024-01-01", "2026-08-04", "1h")
        assert hit is not None
        assert hit.name == filename


class TestFetchOhlcvCacheHit:
    def test_deep_cache_hit_returns_frame_without_network(self, tmp_path, monkeypatch):
        """fetch_ohlcv(use_cache=True) returns the cached frame; no client call."""
        _block_network(monkeypatch)
        _write_tz_aware_cache(
            tmp_path, "MGC_2015-01-01_2026-08-04_1h.csv", "2015-01-01", "2026-08-04"
        )
        df = dl.fetch_ohlcv("MGC", "2024-01-01", "2026-08-04", "1h", use_cache=True)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert str(df.index.tz) == "UTC" or df.index.tz is None
        assert df.index.min() >= pd.Timestamp("2015-01-01", tz="UTC")

    def test_exact_name_cache_hit(self, tmp_path, monkeypatch):
        _block_network(monkeypatch)
        _write_tz_aware_cache(
            tmp_path, "MGC_2024-01-01_2026-08-04_1h.csv", "2024-01-01", "2026-08-04"
        )
        df = dl.fetch_ohlcv("MGC", "2024-01-01", "2026-08-04", "1h", use_cache=True)
        assert len(df) > 0

    def test_cache_miss_then_no_key_returns_empty(self, tmp_path, monkeypatch):
        """No matching cache + no API key => empty frame, no crash, no network."""
        _block_network(monkeypatch)
        monkeypatch.setattr(dl, "_api_key", lambda: "")
        df = dl.fetch_ohlcv("MGC", "2024-01-01", "2026-08-04", "1h", use_cache=True)
        assert df.empty
