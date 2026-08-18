"""
Redis client for JARVIS TRADER signal caching and alert cooldown.

Features:
  - Async Redis connection with connection pooling
  - Graceful fallback to in-memory dict if Redis unavailable
  - Non-blocking init/close (never crashes on connection errors)
"""

import asyncio
import logging
import time
from typing import Any, Optional

try:
    import redis.asyncio as redis
    from redis.exceptions import ConnectionError, RedisError, ResponseError

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global Redis client and fallback cache
_redis_client: Optional[redis.Redis] = None
_fallback_cache: dict[str, Any] = {}  # in-memory cache if Redis unavailable
_redis_enabled = True  # Track whether Redis is actually working

# Cache statistics
_cache_hits = 0
_cache_misses = 0


async def init_redis(redis_url: str) -> bool:
    """
    Initialize async Redis client with connection pooling.

    Args:
        redis_url: Connection string (e.g., "redis://localhost:6379")

    Returns:
        bool: True if Redis initialized successfully, False if using fallback
    """
    global _redis_client, _redis_enabled

    if not REDIS_AVAILABLE:
        logger.warning("redis module not available — using in-memory cache fallback")
        _redis_enabled = False
        return False

    try:
        # Parse connection URL and create connection pool
        _redis_client = await redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )

        # Test connection
        await _redis_client.ping()
        logger.info(f"✅ Redis connected: {redis_url}")
        _redis_enabled = True
        return True

    except (ConnectionError, RedisError, ResponseError, asyncio.TimeoutError) as e:
        logger.warning(f"⚠️  Redis unavailable ({type(e).__name__}: {e}) — using in-memory cache")
        _redis_client = None
        _redis_enabled = False
        return False
    except Exception as e:
        logger.warning(f"⚠️  Redis init failed: {e} — using in-memory cache")
        _redis_client = None
        _redis_enabled = False
        return False


async def close_redis() -> None:
    """Gracefully close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.close()
            logger.info("✅ Redis connection closed")
        except Exception as e:
            logger.warning(f"Error closing Redis: {e}")
        finally:
            _redis_client = None


def get_redis_client() -> Optional[redis.Redis]:
    """Get current Redis client, or None if using fallback."""
    return _redis_client if _redis_enabled else None


async def get(key: str) -> Any | None:
    """
    Get value from Redis or fallback cache.

    Args:
        key: Cache key

    Returns:
        Cached value or None
    """
    if _redis_enabled and _redis_client is not None:
        try:
            value = await _redis_client.get(key)
            return value
        except Exception as e:
            logger.debug(f"Redis GET failed for {key}: {e} — trying fallback")
            return _fallback_get(key)
    else:
        return _fallback_get(key)


def _fallback_get(key: str) -> Any | None:
    """Fallback-cache read honoring TTL (2026-08-18 fix).

    The old fallback ignored TTL entirely — with Redis down, a pipeline
    signal cached at 08:04 (stale bars) was served forever, so every
    /pipeline/run short-circuited on the cached HOLD with 0 LLM calls.
    Entries now expire after their TTL, mirroring Redis setex semantics.
    """
    entry = _fallback_cache.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if expires_at is not None and time.time() > expires_at:
        _fallback_cache.pop(key, None)
        return None
    return value


async def set(key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
    """
    Set value in Redis or fallback cache.

    Args:
        key: Cache key
        value: Value to cache (must be string or JSON-serializable)
        ttl_seconds: Time-to-live in seconds (None = no expiry)

    Returns:
        bool: True if set successfully, False on error
    """
    if _redis_enabled and _redis_client is not None:
        try:
            if ttl_seconds is not None:
                await _redis_client.setex(key, ttl_seconds, value)
            else:
                await _redis_client.set(key, value)
            return True
        except Exception as e:
            logger.debug(f"Redis SET failed for {key}: {e} — using fallback")
            _fallback_cache[key] = (
                value,
                time.time() + ttl_seconds if ttl_seconds is not None else None,
            )
            return True
    else:
        _fallback_cache[key] = (
            value,
            time.time() + ttl_seconds if ttl_seconds is not None else None,
        )
        return True


async def delete(key: str) -> bool:
    """
    Delete key from Redis or fallback cache.

    Args:
        key: Cache key

    Returns:
        bool: True if deleted, False if not found or error
    """
    if _redis_enabled and _redis_client is not None:
        try:
            result = await _redis_client.delete(key)
            return result > 0
        except Exception as e:
            logger.debug(f"Redis DELETE failed for {key}: {e} — trying fallback")
            if key in _fallback_cache:
                del _fallback_cache[key]
                return True
            return False
    else:
        if key in _fallback_cache:
            del _fallback_cache[key]
            return True
        return False


async def exists(key: str) -> bool:
    """
    Check if key exists in Redis or fallback cache.

    Args:
        key: Cache key

    Returns:
        bool: True if key exists
    """
    if _redis_enabled and _redis_client is not None:
        try:
            result = await _redis_client.exists(key)
            return result > 0
        except Exception as e:
            logger.debug(f"Redis EXISTS failed for {key}: {e} — trying fallback")
            return key in _fallback_cache
    else:
        return key in _fallback_cache


async def flushdb() -> bool:
    """Flush all cache entries (Redis only, does not clear fallback)."""
    if _redis_enabled and _redis_client is not None:
        try:
            await _redis_client.flushdb()
            logger.info("✅ Redis cache flushed")
            return True
        except Exception as e:
            logger.warning(f"Failed to flush Redis: {e}")
            return False
    return True


def get_cache_stats() -> dict:
    """Get cache hit/miss statistics and Redis status."""
    global _cache_hits, _cache_misses
    total = _cache_hits + _cache_misses
    hit_rate = (_cache_hits / total * 100) if total > 0 else 0
    return {
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "total_accesses": total,
        "hit_rate_percent": round(hit_rate, 2),
        "redis_connected": get_redis_client() is not None,
    }


def reset_cache_stats() -> None:
    """Reset cache statistics."""
    global _cache_hits, _cache_misses
    _cache_hits = 0
    _cache_misses = 0


def increment_hit() -> None:
    """Increment cache hit counter."""
    global _cache_hits
    _cache_hits += 1


def increment_miss() -> None:
    """Increment cache miss counter."""
    global _cache_misses
    _cache_misses += 1
