"""Offline tests for the OPRA (equity/index options) fetch path.

These cover everything that does NOT require a live key: cache-path naming,
the watchlist contract, the dark-mode degradation, and the unknown-underlying
warning. The network path is deliberately unverified until
DATABENTO_API_KEY exists — see the UNVERIFIED note in databento_loader.py.
"""

from __future__ import annotations

import sys

import pandas as pd
import pytest

from backtest import databento_loader as dl


class TestOptionsWatchlist:
    def test_watchlist_matches_the_options_underlyings(self):
        # The JARVIS options universe: equity/index names the engine routes.
        assert set(dl.OPTIONS_WATCHLIST) == {"SPY", "QQQ", "AAPL", "TSLA", "SPX", "VIX"}

    def test_opra_dataset_code(self):
        assert dl.OPRA_DATASET == "OPRA.PILLAR"

    def test_cache_path_is_distinct_from_futures_caches(self):
        opt = dl._opt_cache_path("SPY", "2013-01-01", "2026-09-23", "ohlcv-1d")
        fut = dl._cache_path("MES", "2015-01-01", "2026-09-23", "1h")
        assert opt.name.startswith("SPY_OPT_")
        assert opt != fut
        assert opt.parent == fut.parent == dl.CACHE_DIR

    def test_cache_path_sanitises_colons_and_slashes(self):
        p = dl._opt_cache_path("SPX", "2013-01-01T00:00", "2026-09-23T00:00", "ohlcv-1m")
        assert ":" not in p.name and "/" not in p.name


class TestDarkMode:
    """Absence of the key must degrade cleanly — no exception, no partial write."""

    def test_chains_empty_without_key(self, monkeypatch):
        monkeypatch.setattr(dl, "_api_key", lambda: "")
        out = dl.fetch_option_chains("SPY", "2013-01-01", "2026-09-23", use_cache=False)
        assert isinstance(out, pd.DataFrame) and out.empty

    def test_definitions_empty_without_key(self, monkeypatch):
        monkeypatch.setattr(dl, "_api_key", lambda: "")
        out = dl.fetch_option_definitions("SPY", "2013-01-01", "2026-09-23", use_cache=False)
        assert isinstance(out, pd.DataFrame) and out.empty

    def test_placeholder_key_is_treated_as_dark(self, monkeypatch):
        monkeypatch.setattr(dl, "_api_key", lambda: "your_databento_key_here")
        out = dl.fetch_option_chains("QQQ", "2013-01-01", "2026-09-23", use_cache=False)
        assert out.empty

    def test_missing_package_degrades(self, monkeypatch):
        monkeypatch.setattr(dl, "_api_key", lambda: "db-fake-key")
        monkeypatch.setitem(sys.modules, "databento", None)
        out = dl.fetch_option_chains("SPY", "2013-01-01", "2026-09-23", use_cache=False)
        assert out.empty


class TestUnknownUnderlying:
    def test_unknown_underlying_warns_but_does_not_raise(self, monkeypatch, capsys):
        monkeypatch.setattr(dl, "_api_key", lambda: "")
        out = dl.fetch_option_chains("NOTASYMBOL", "2013-01-01", "2026-09-23", use_cache=False)
        assert out.empty
        assert "OPTIONS_WATCHLIST" in capsys.readouterr().out


class TestCacheReuse:
    def test_existing_cache_is_read_without_network(self, monkeypatch, tmp_path):
        cache = tmp_path / "SPY_OPT_2013-01-01_2026-09-23_ohlcv-1d.csv"
        pd.DataFrame({
            "timestamp": ["2026-01-02T00:00:00Z"], "instrument_id": [1],
            "raw_symbol": ["SPY   260116C00500000"], "expiration": ["2026-01-16"],
            "strike_price": [500.0], "instrument_class": ["C"],
            "open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05], "volume": [10],
        }).to_csv(cache, index=False)
        monkeypatch.setattr(dl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(dl, "_api_key", lambda: "db-fake-key")
        monkeypatch.setitem(sys.modules, "databento", None)  # network path must not run
        out = dl.fetch_option_chains("SPY", "2013-01-01", "2026-09-23")
        assert len(out) == 1
        assert out.iloc[0]["raw_symbol"].startswith("SPY")
