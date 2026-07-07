"""
Tests for the Speculation/Pre-execution Engine.
Covers PrefetchCache TTL semantics and SpeculationEngine singleton/caching behavior.
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# Allow both `pytest engine/tests/` and `cd engine && pytest tests/` invocations
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestPrefetchCache:
    def setup_method(self):
        from speculation.prefetch_cache import PrefetchCache

        self.cache = PrefetchCache(ttl_seconds=2)  # 2s TTL for fast tests

    def test_set_and_get(self):
        self.cache.set("key1", {"value": 42})
        result = self.cache.get("key1")
        assert result == {"value": 42}

    def test_miss_returns_none(self):
        assert self.cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        self.cache.set("expiring", "data", ttl=1)
        assert self.cache.get("expiring") == "data"
        time.sleep(1.1)
        assert self.cache.get("expiring") is None

    def test_has_returns_true_for_valid(self):
        self.cache.set("present", True)
        assert self.cache.has("present")

    def test_has_returns_false_for_missing(self):
        assert not self.cache.has("missing")

    def test_invalidate_removes_key(self):
        self.cache.set("remove_me", 123)
        self.cache.invalidate("remove_me")
        assert self.cache.get("remove_me") is None

    def test_invalidate_nonexistent_is_noop(self):
        # Should not raise
        self.cache.invalidate("ghost_key")

    def test_clear_removes_all(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        assert self.cache.get("a") is None
        assert self.cache.get("b") is None

    def test_stats(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        stats = self.cache.stats()
        assert stats["valid_keys"] >= 2
        assert "ttl_seconds" in stats
        assert stats["ttl_seconds"] == 2

    def test_stats_counts_expired(self):
        self.cache.set("expiring_stat", "x", ttl=1)
        time.sleep(1.1)
        stats = self.cache.stats()
        # After expiry the key is still in _store until accessed;
        # stats counts it as expired (not evicted until next get)
        assert stats["expired_keys"] >= 1

    def test_keys_by_prefix(self):
        self.cache.set("indicators:MES:1h", {})
        self.cache.set("indicators:MNQ:1h", {})
        self.cache.set("bars:MES:1h", {})
        keys = self.cache.keys_by_prefix("indicators:")
        assert "indicators:MES:1h" in keys
        assert "indicators:MNQ:1h" in keys
        assert "bars:MES:1h" not in keys

    def test_keys_by_prefix_excludes_expired(self):
        self.cache.set("indicators:EXPIRED:1h", {}, ttl=1)
        time.sleep(1.1)
        keys = self.cache.keys_by_prefix("indicators:")
        assert "indicators:EXPIRED:1h" not in keys

    def test_overwrite_key_resets_ttl(self):
        self.cache.set("refresh", "old", ttl=1)
        time.sleep(0.5)
        # Overwrite with longer TTL
        self.cache.set("refresh", "new", ttl=5)
        time.sleep(0.8)  # Would have expired on old TTL
        assert self.cache.get("refresh") == "new"


class TestSpeculationEngine:
    def setup_method(self):
        from speculation.engine import SpeculationEngine

        config = MagicMock()
        config.FUTURES_WATCHLIST = ["MES"]
        config.OPTIONS_WATCHLIST = []
        self.engine = SpeculationEngine(config=config, data_manager=None)

    @pytest.mark.asyncio
    async def test_speculate_no_data_manager(self):
        result = await self.engine.speculate()
        assert "symbols_processed" in result
        assert result["symbols_processed"] == 0  # No data manager = no data
        assert result["symbols_requested"] == 1  # MES was in watchlist
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_speculate_increments_count(self):
        await self.engine.speculate()
        await self.engine.speculate()
        assert self.engine._speculation_count == 2

    @pytest.mark.asyncio
    async def test_speculate_returns_errors_list(self):
        result = await self.engine.speculate()
        assert "errors" in result
        assert isinstance(result["errors"], list)

    def test_get_status(self):
        status = self.engine.get_status()
        assert "speculation_count" in status
        assert "cache" in status
        assert "cache_hits" in status
        assert "running" in status
        assert "cached_symbols" in status

    def test_get_status_last_speculation_none_initially(self):
        status = self.engine.get_status()
        assert status["last_speculation"] is None

    @pytest.mark.asyncio
    async def test_get_status_last_speculation_set_after_cycle(self):
        await self.engine.speculate()
        status = self.engine.get_status()
        assert status["last_speculation"] is not None

    def test_cache_hit_recording(self):
        self.engine.record_cache_hit()
        self.engine.record_cache_hit()
        assert self.engine._cache_hits == 2

    def test_get_cached_indicators_miss(self):
        result = self.engine.get_cached_indicators("MES")
        assert result is None

    def test_set_and_get_cached_indicators(self):
        self.engine.cache.set("indicators:MES:1h", {"stc_val": 45.0, "atr": 12.5})
        result = self.engine.get_cached_indicators("MES")
        assert result["stc_val"] == 45.0

    def test_get_cached_bars_miss(self):
        assert self.engine.get_cached_bars("MES") is None

    def test_set_and_get_cached_bars(self):
        import pandas as pd

        fake_bars = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        self.engine.cache.set("bars:MES:1h", fake_bars)
        result = self.engine.get_cached_bars("MES")
        assert result is not None
        assert len(result) == 3

    def test_singleton_pattern(self):
        from speculation.engine import get_speculation_engine, set_speculation_engine

        mock = MagicMock()
        set_speculation_engine(mock)
        assert get_speculation_engine() is mock
        # Cleanup — reset to None so other tests are not affected
        set_speculation_engine(None)

    def test_singleton_default_none(self):
        from speculation.engine import get_speculation_engine, set_speculation_engine

        set_speculation_engine(None)
        assert get_speculation_engine() is None

    @pytest.mark.asyncio
    async def test_prefetch_market_data_no_data_manager(self):
        result = await self.engine.prefetch_market_data("MES")
        assert result is None

    @pytest.mark.asyncio
    async def test_prefetch_market_data_returns_cached(self):
        import pandas as pd

        fake_bars = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        self.engine.cache.set("bars:MES:1h", fake_bars)
        result = await self.engine.prefetch_market_data("MES")
        assert result is not None

    @pytest.mark.asyncio
    async def test_precompute_indicators_no_bars_returns_none(self):
        result = await self.engine.precompute_indicators("MES")
        assert result is None

    @pytest.mark.asyncio
    async def test_precompute_indicators_with_mock_data_manager(self):
        """SpeculationEngine with a mock data manager that returns bars."""
        import pandas as pd

        from speculation.engine import SpeculationEngine

        mock_dm = MagicMock()
        fake_bars = pd.DataFrame(
            {
                "open": [100.0] * 60,
                "high": [102.0] * 60,
                "low": [98.0] * 60,
                "close": [101.0] * 60,
                "volume": [1000.0] * 60,
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=fake_bars)

        config = MagicMock()
        config.FUTURES_WATCHLIST = ["MES"]
        config.OPTIONS_WATCHLIST = []

        engine = SpeculationEngine(config=config, data_manager=mock_dm)
        bars = await engine.prefetch_market_data("MES")
        assert bars is not None
        # Indicators may or may not compute depending on backtest.signals availability
        # but we should not raise
        await engine.precompute_indicators("MES", bars)
