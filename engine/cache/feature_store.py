"""
Feature/indicator store for JARVIS TRADER.

Pre-computes and caches technical indicators for fast lookup across pipeline stages.
Avoids redundant indicator calculations.

Key format: "jarvis:indicators:{symbol}:{timeframe}"
"""

import json
import logging
from typing import Any, Optional

from . import redis_client

logger = logging.getLogger(__name__)

# Default TTL for indicator cache: 5 minutes (indicators can change frequently)
DEFAULT_INDICATOR_CACHE_TTL = 300


async def store_indicators(
    symbol: str,
    timeframe: str,
    indicators_dict: dict[str, Any],
    ttl_seconds: int = DEFAULT_INDICATOR_CACHE_TTL,
) -> bool:
    """
    Store pre-computed indicators for a symbol/timeframe combo.

    Args:
        symbol: Trading symbol (e.g., "MES")
        timeframe: Timeframe (e.g., "5m", "15m", "1h", "1d")
        indicators_dict: Dict of indicator values (e.g., {"rsi": 65, "macd": 0.5, ...})
        ttl_seconds: Time-to-live (default 300 = 5 min)

    Returns:
        bool: True if stored successfully
    """
    key = f"jarvis:indicators:{symbol}:{timeframe}"
    try:
        # Serialize to JSON
        json_data = json.dumps(indicators_dict, default=str)
        success = await redis_client.set(key, json_data, ttl_seconds=ttl_seconds)
        if success:
            logger.debug(f"Cached indicators for {symbol}/{timeframe} ({ttl_seconds}s)")
        return success
    except Exception as e:
        logger.warning(f"Failed to cache indicators for {symbol}/{timeframe}: {e}")
        return False


async def get_indicators(
    symbol: str,
    timeframe: str,
) -> Optional[dict[str, Any]]:
    """
    Retrieve cached indicators for a symbol/timeframe combo.

    Args:
        symbol: Trading symbol
        timeframe: Timeframe

    Returns:
        Indicators dict, or None if not found or expired
    """
    key = f"jarvis:indicators:{symbol}:{timeframe}"
    try:
        json_data = await redis_client.get(key)
        if json_data is None:
            return None

        # Deserialize from JSON
        indicators = json.loads(json_data)
        logger.debug(f"Retrieved cached indicators for {symbol}/{timeframe}")
        return indicators

    except json.JSONDecodeError:
        logger.warning(f"Corrupted indicator cache for {symbol}/{timeframe} — skipping")
        await redis_client.delete(key)
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve indicators for {symbol}/{timeframe}: {e}")
        return None


async def invalidate_indicators(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> bool:
    """
    Invalidate cached indicators.

    Args:
        symbol: Symbol to clear (if None, clears all)
        timeframe: Timeframe to clear (if None, clears all)

    Returns:
        bool: True if successful
    """
    if symbol is None and timeframe is None:
        # Clear all indicator cache
        logger.info("Clearing all indicator cache")
        try:
            redis_client_obj = redis_client.get_redis_client()
            if redis_client_obj is not None:
                cursor = 0
                deleted = 0
                while True:
                    cursor, keys = await redis_client_obj.scan(
                        cursor,
                        match="jarvis:indicators:*"
                    )
                    if keys:
                        await redis_client_obj.delete(*keys)
                        deleted += len(keys)
                    if cursor == 0:
                        break
                logger.info(f"Deleted {deleted} indicator entries")
                return True
            else:
                logger.warning("Redis not available — cannot clear indicator cache")
                return False
        except Exception as e:
            logger.warning(f"Failed to clear indicator cache: {e}")
            return False

    else:
        # Clear specific symbol/timeframe
        if symbol and timeframe:
            key = f"jarvis:indicators:{symbol}:{timeframe}"
        elif symbol:
            key = f"jarvis:indicators:{symbol}:*"
        else:
            key = f"jarvis:indicators:*:{timeframe}"

        try:
            if "*" in key:
                redis_client_obj = redis_client.get_redis_client()
                if redis_client_obj is not None:
                    cursor = 0
                    deleted = 0
                    while True:
                        cursor, keys = await redis_client_obj.scan(cursor, match=key)
                        if keys:
                            await redis_client_obj.delete(*keys)
                            deleted += len(keys)
                        if cursor == 0:
                            break
                    logger.debug(f"Cleared {deleted} indicator entries for {key}")
                    return True
                else:
                    return False
            else:
                result = await redis_client.delete(key)
                if result:
                    logger.debug(f"Cleared indicators for {symbol}/{timeframe}")
                return result

        except Exception as e:
            logger.warning(f"Failed to clear indicators: {e}")
            return False
