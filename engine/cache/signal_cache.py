"""
Pipeline signal result caching for JARVIS TRADER.

Caches complete pipeline_result dicts per symbol with configurable TTL.
Avoids redundant LLM calls when signal regime hasn't changed.

Key format: "jarvis:signal:{symbol}"
"""

import json
import logging
from typing import Any, Optional

from . import redis_client

logger = logging.getLogger(__name__)

# Default TTL for cached signals: 30 minutes
DEFAULT_SIGNAL_CACHE_TTL = 1800


async def cache_signal(
    symbol: str,
    pipeline_result: dict,
    ttl_seconds: int = DEFAULT_SIGNAL_CACHE_TTL,
) -> bool:
    """
    Cache a pipeline result for a symbol.

    Args:
        symbol: Trading symbol (e.g., "MES", "MNQ")
        pipeline_result: Complete dict returned from TradingPipeline.analyze_and_decide()
        ttl_seconds: Time-to-live in seconds (default 1800 = 30 min)

    Returns:
        bool: True if cached successfully
    """
    key = f"jarvis:signal:{symbol}"
    try:
        # Serialize to JSON for storage
        json_data = json.dumps(pipeline_result, default=str)
        success = await redis_client.set(key, json_data, ttl_seconds=ttl_seconds)
        if success:
            logger.debug(f"Cached signal for {symbol} (TTL={ttl_seconds}s)")
        return success
    except Exception as e:
        logger.warning(f"Failed to cache signal for {symbol}: {e}")
        return False


async def get_cached_signal(symbol: str) -> Optional[dict]:
    """
    Retrieve cached pipeline result for a symbol.

    Args:
        symbol: Trading symbol (e.g., "MES", "MNQ")

    Returns:
        Cached pipeline_result dict, or None if not found or expired
    """
    key = f"jarvis:signal:{symbol}"
    try:
        json_data = await redis_client.get(key)
        if json_data is None:
            return None

        # Deserialize from JSON
        cached_result = json.loads(json_data)
        logger.debug(f"Retrieved cached signal for {symbol}")
        return cached_result

    except json.JSONDecodeError:
        logger.warning(f"Corrupted cache entry for {symbol} — skipping")
        await redis_client.delete(key)
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve cached signal for {symbol}: {e}")
        return None


async def invalidate_signal(symbol: str) -> bool:
    """
    Invalidate (delete) cached signal for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        bool: True if deleted
    """
    key = f"jarvis:signal:{symbol}"
    try:
        result = await redis_client.delete(key)
        if result:
            logger.debug(f"Invalidated cached signal for {symbol}")
        return result
    except Exception as e:
        logger.warning(f"Failed to invalidate cache for {symbol}: {e}")
        return False


async def should_use_cache(
    symbol: str,
    current_regime: Optional[str] = None,
) -> bool:
    """
    Determine if cached signal should be used.

    Uses cache if:
      1. Signal exists in cache (not expired)
      2. Market regime matches cached regime (if provided)

    Args:
        symbol: Trading symbol
        current_regime: Current market regime (optional). If provided, only use cache
                       if cached regime matches.

    Returns:
        bool: True if cached signal is valid and should be used
    """
    cached = await get_cached_signal(symbol)
    if cached is None:
        from . import redis_client
        redis_client.increment_miss()
        return False

    # If regime checking is enabled, verify regime match
    if current_regime is not None:
        cached_regime = cached.get("analyst_reports", {}).get("technical", {}).get("regime")
        if cached_regime and cached_regime != current_regime:
            logger.debug(f"{symbol}: regime changed ({cached_regime} -> {current_regime}) — rerunning pipeline")
            from . import redis_client
            redis_client.increment_miss()
            return False

    logger.debug(f"{symbol}: using cached signal")
    from . import redis_client
    redis_client.increment_hit()
    return True


async def invalidate_all() -> bool:
    """Invalidate all cached signals (flush cache)."""
    try:
        success = await redis_client.flushdb()
        if success:
            logger.info("✅ All cached signals invalidated")
        return success
    except Exception as e:
        logger.warning(f"Failed to invalidate all signals: {e}")
        return False
