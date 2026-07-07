"""
Speculation/Pre-execution Engine — adapted from Claude Code's speculation feature.
Pre-computes likely next pipeline inputs during idle periods to reduce latency.
"""

import logging
from datetime import datetime
from typing import Optional

from .prefetch_cache import PrefetchCache

logger = logging.getLogger(__name__)

_speculation_instance: Optional["SpeculationEngine"] = None


def get_speculation_engine() -> Optional["SpeculationEngine"]:
    return _speculation_instance


def set_speculation_engine(engine: "SpeculationEngine") -> None:
    global _speculation_instance
    _speculation_instance = engine


class SpeculationEngine:
    """
    Pre-computes market data and technical indicators during idle periods.
    Results are cached for PREFETCH_TTL_SECONDS (default: 10 min).

    Pipeline agents check PrefetchCache before computing — if cache hit,
    latency drops from ~20s (data fetch + compute) to ~1s (cache lookup).
    """

    def __init__(self, config, data_manager=None, prefetch_ttl: int = 600):
        self._config = config
        self._data = data_manager
        self.cache = PrefetchCache(ttl_seconds=prefetch_ttl)
        self._speculation_count = 0
        self._cache_hits = 0  # Tracked externally by pipeline
        self._last_speculation: Optional[datetime] = None
        self._running = False

    async def speculate(self) -> dict:
        """
        Run one speculation cycle:
        1. Pre-fetch OHLCV data for all watchlist symbols
        2. Pre-compute technical indicators (STC, ATR, regime state)
        3. Cache results for pipeline consumption
        Returns: dict with symbols_processed, cache_size, duration_ms
        """
        start = datetime.now()
        self._speculation_count += 1

        watchlist = list(getattr(self._config, "FUTURES_WATCHLIST", ["MES", "MNQ"]))
        # Add options watchlist if available
        options_list = list(getattr(self._config, "OPTIONS_WATCHLIST", []))
        all_symbols = list(set(watchlist + options_list))

        processed = []
        errors = []

        for symbol in all_symbols:
            try:
                # Pre-fetch market data
                bars = await self.prefetch_market_data(symbol)
                if bars is not None:
                    # Pre-compute indicators
                    indicators = await self.precompute_indicators(symbol, bars)
                    if indicators:
                        self.cache.set(f"indicators:{symbol}:1h", indicators)
                        processed.append(symbol)
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
                logger.debug(f"Speculation failed for {symbol}: {e}")

        self._last_speculation = datetime.now()
        duration_ms = (datetime.now() - start).total_seconds() * 1000

        result = {
            "speculation_count": self._speculation_count,
            "symbols_processed": len(processed),
            "symbols_requested": len(all_symbols),
            "symbols": processed,
            "errors": errors,
            "cache_size": self.cache.stats()["valid_keys"],
            "duration_ms": round(duration_ms, 1),
        }

        logger.debug(
            f"Speculation cycle complete: {len(processed)}/{len(all_symbols)} symbols "
            f"in {duration_ms:.0f}ms"
        )
        return result

    async def prefetch_market_data(self, symbol: str, interval: str = "1h", limit: int = 100):
        """Fetch and cache OHLCV bars for a symbol."""
        cache_key = f"bars:{symbol}:{interval}"

        # Return cached if fresh
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._data:
            return None

        try:
            # Try get_bars method (check actual signature in market_data.py)
            if hasattr(self._data, "get_bars"):
                bars = await self._data.get_bars(symbol, interval=interval, limit=limit)
            elif hasattr(self._data, "fetch_bars"):
                bars = await self._data.fetch_bars(symbol, interval=interval, limit=limit)
            else:
                return None

            if bars is not None and len(bars) > 0:
                self.cache.set(cache_key, bars, ttl=300)  # 5 min TTL for raw bars
                return bars
        except Exception as e:
            logger.debug(f"prefetch_market_data {symbol}: {e}")
        return None

    async def precompute_indicators(self, symbol: str, bars=None) -> Optional[dict]:
        """Compute technical indicators and cache results."""
        cache_key = f"indicators:{symbol}:1h"

        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if bars is None:
            bars = self.cache.get(f"bars:{symbol}:1h")

        if bars is None:
            return None

        try:
            # Import signals computation — compute_all_indicators returns a DataFrame,
            # so we extract the last row as a dict for caching
            from backtest.signals import compute_all_indicators

            indicators_df = compute_all_indicators(bars)
            if indicators_df is not None and len(indicators_df) > 0:
                last = indicators_df.iloc[-1]
                result = {
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                    "cached_at": datetime.now().isoformat(),
                }
                # Safely extract key indicator columns
                for col in ("stc_val", "stc_signal", "atr", "kama_val", "kama_signal"):
                    if col in last.index:
                        val = last[col]
                        # Convert numpy scalar to Python native type
                        try:
                            result[col] = (
                                float(val) if col not in ("stc_signal", "kama_signal") else str(val)
                            )
                        except (TypeError, ValueError):
                            result[col] = str(val)
                self.cache.set(cache_key, result, ttl=600)
                return result
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"precompute_indicators {symbol}: {e}")

        # Fallback: compute basic price info from raw bars
        try:
            if hasattr(bars, "iloc"):
                latest = bars.iloc[-1]
                result = {
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                    "price": float(latest.get("close", latest.get("Close", 0))),
                    "volume": (
                        float(latest.get("volume", latest.get("Volume", 0)))
                        if "volume" in latest.index or "Volume" in latest.index
                        else 0
                    ),
                    "cached_at": datetime.now().isoformat(),
                }
                self.cache.set(cache_key, result, ttl=600)
                return result
        except Exception:
            pass

        return None

    def get_cached_indicators(self, symbol: str, interval: str = "1h") -> Optional[dict]:
        """Pipeline-facing: get pre-computed indicators (synchronous)."""
        return self.cache.get(f"indicators:{symbol}:{interval}")

    def get_cached_bars(self, symbol: str, interval: str = "1h"):
        """Pipeline-facing: get pre-fetched bars (synchronous)."""
        return self.cache.get(f"bars:{symbol}:{interval}")

    def record_cache_hit(self) -> None:
        """Called by pipeline when it successfully uses cached data."""
        self._cache_hits += 1

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "speculation_count": self._speculation_count,
            "cache_hits": self._cache_hits,
            "last_speculation": (
                self._last_speculation.isoformat() if self._last_speculation else None
            ),
            "cache": self.cache.stats(),
            "cached_symbols": self.cache.keys_by_prefix("indicators:"),
        }
