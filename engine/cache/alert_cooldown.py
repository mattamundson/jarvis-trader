"""
Alert cooldown tracking for JARVIS TRADER.

Prevents alert spam by tracking per-symbol/per-channel cooldown windows.
Survives restarts via Redis; falls back to in-memory dict if Redis unavailable.

Key format: "jarvis:cooldown:{channel}:{symbol}"
Channels: "whatsapp", "email", "discord", etc.
"""

import logging
from typing import Optional

from . import redis_client

logger = logging.getLogger(__name__)

# Default cooldown: 2 hours (7200 seconds)
DEFAULT_COOLDOWN_SECONDS = 7200


async def set_cooldown(
    symbol: str,
    channel: str = "whatsapp",
    seconds: int = DEFAULT_COOLDOWN_SECONDS,
) -> bool:
    """
    Set alert cooldown for a symbol+channel combo.

    Once set, is_on_cooldown(symbol, channel) will return True until TTL expires.

    Args:
        symbol: Trading symbol (e.g., "MES")
        channel: Alert channel (e.g., "whatsapp", "email", "discord")
        seconds: Cooldown duration (default 7200 = 2 hours)

    Returns:
        bool: True if cooldown set successfully
    """
    key = f"jarvis:cooldown:{channel}:{symbol}"
    try:
        # Store a marker value; TTL is enforced by Redis expiry
        success = await redis_client.set(key, "1", ttl_seconds=seconds)
        if success:
            logger.debug(f"Cooldown set for {symbol}/{channel} ({seconds}s)")
        return success
    except Exception as e:
        logger.warning(f"Failed to set cooldown for {symbol}/{channel}: {e}")
        return False


async def is_on_cooldown(
    symbol: str,
    channel: str = "whatsapp",
) -> bool:
    """
    Check if alert cooldown is active for symbol+channel.

    Args:
        symbol: Trading symbol
        channel: Alert channel

    Returns:
        bool: True if on cooldown (alert should be suppressed)
    """
    key = f"jarvis:cooldown:{channel}:{symbol}"
    try:
        exists = await redis_client.exists(key)
        if exists:
            logger.debug(f"Cooldown active for {symbol}/{channel}")
        return exists
    except Exception as e:
        logger.warning(f"Failed to check cooldown for {symbol}/{channel}: {e}")
        return False  # On error, allow alert to proceed


async def clear_cooldown(
    symbol: str,
    channel: str = "whatsapp",
) -> bool:
    """
    Manually clear cooldown for a symbol+channel.

    Args:
        symbol: Trading symbol
        channel: Alert channel

    Returns:
        bool: True if cleared
    """
    key = f"jarvis:cooldown:{channel}:{symbol}"
    try:
        result = await redis_client.delete(key)
        if result:
            logger.debug(f"Cooldown cleared for {symbol}/{channel}")
        return result
    except Exception as e:
        logger.warning(f"Failed to clear cooldown for {symbol}/{channel}: {e}")
        return False


async def clear_all_cooldowns(symbol: Optional[str] = None) -> bool:
    """
    Clear all cooldowns, optionally filtered by symbol.

    Args:
        symbol: Optional symbol to filter by. If None, clears all cooldowns.

    Returns:
        bool: True if successful
    """
    if symbol is None:
        logger.info("Clearing all cooldowns")
    else:
        logger.info(f"Clearing all cooldowns for {symbol}")

    try:
        # Note: in-memory fallback doesn't support pattern deletion
        # For simplicity, just log warning if using fallback
        redis_client_obj = redis_client.get_redis_client()
        if redis_client_obj is not None:
            pattern = f"jarvis:cooldown:*:{symbol}" if symbol else "jarvis:cooldown:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await redis_client_obj.scan(cursor, match=pattern)
                if keys:
                    await redis_client_obj.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            logger.info(f"Deleted {deleted} cooldown entries")
            return True
        else:
            logger.warning("Redis not available — cannot clear all cooldowns")
            return False

    except Exception as e:
        logger.warning(f"Failed to clear cooldowns: {e}")
        return False
