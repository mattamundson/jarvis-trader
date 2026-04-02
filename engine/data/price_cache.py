"""
Price caching with TTL and Polygon rate limit handling.
In-memory cache using stdlib only (no redis, no third-party libs).
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Cache configuration (no magic numbers)
CACHE_TTL_SECONDS = 60
MAX_RETRIES = 3
RETRY_DELAYS_SECONDS = [1, 2, 4]  # Exponential backoff: 1s, 2s, 4s


class PriceCache:
    """
    Thread-safe in-memory price cache with TTL.
    Handles Polygon 429 (rate limit) errors by returning expired cache if available.
    """

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._cache: dict[str, dict] = {}  # {symbol: {data: {...}, timestamp: float}}
        self._lock = asyncio.Lock()

    async def get(self, symbol: str) -> Optional[dict]:
        """
        Get cached price data if within TTL.
        Returns None if cache miss or expired.
        """
        async with self._lock:
            if symbol not in self._cache:
                return None

            cached = self._cache[symbol]
            age = time.time() - cached["timestamp"]

            if age > self._ttl:
                logger.debug(f"Price cache expired for {symbol} (age {age:.1f}s > {self._ttl}s)")
                return None

            logger.debug(f"Price cache hit for {symbol} (age {age:.1f}s)")
            return cached["data"]

    async def get_expired(self, symbol: str) -> Optional[dict]:
        """
        Get cached price data even if expired.
        Used as fallback when Polygon returns 429 (Too Many Requests).
        """
        async with self._lock:
            if symbol in self._cache:
                return self._cache[symbol]["data"]
            return None

    async def set(self, symbol: str, data: dict) -> None:
        """
        Store price data with current timestamp.
        """
        async with self._lock:
            self._cache[symbol] = {
                "data": data,
                "timestamp": time.time(),
            }
            logger.debug(f"Price cache set for {symbol}")

    async def clear(self, symbol: Optional[str] = None) -> None:
        """
        Clear cache for symbol, or all symbols if None.
        """
        async with self._lock:
            if symbol:
                self._cache.pop(symbol, None)
                logger.debug(f"Price cache cleared for {symbol}")
            else:
                self._cache.clear()
                logger.debug("Price cache cleared (all)")


async def retry_with_backoff(
    fetch_func,
    symbol: str,
    cache: PriceCache,
    max_retries: int = MAX_RETRIES,
    retry_delays: list[int] = RETRY_DELAYS_SECONDS,
) -> Optional[dict]:
    """
    Retry fetching with exponential backoff.
    On 429 (rate limit), return expired cache if available.
    On other errors, retry up to max_retries times.
    fetch_func should be a callable that returns data (already bound with symbol).
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            result = await fetch_func()
            if result:
                await cache.set(symbol, result)
            return result
        except Exception as e:
            error_msg = str(e).lower()
            last_error = e

            # 429 (Too Many Requests) — return expired cache if available
            if "429" in error_msg or "too many requests" in error_msg:
                logger.warning(
                    f"Polygon rate limit (429) for {symbol} — "
                    f"returning expired cache if available"
                )
                expired = await cache.get_expired(symbol)
                if expired:
                    return expired
                return None

            # Other errors — retry with backoff
            if attempt < max_retries - 1:
                delay = retry_delays[attempt] if attempt < len(retry_delays) else 4
                logger.warning(
                    f"Price fetch failed for {symbol} (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"Price fetch failed for {symbol} after {max_retries} retries: {e}")

    # All retries exhausted
    if last_error:
        raise last_error
    return None
