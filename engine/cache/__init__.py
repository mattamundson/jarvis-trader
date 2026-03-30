"""
JARVIS TRADER — Caching layer using Redis with graceful fallback

Provides:
  - Async Redis client with connection pooling
  - Signal result caching (30-min TTL by default)
  - Alert cooldown tracking (2-hour TTL by default)
  - Feature/indicator pre-computation storage

If Redis is unavailable, falls back to in-memory dict cache (non-persistent).
"""

from .alert_cooldown import clear_cooldown, is_on_cooldown, set_cooldown
from .feature_store import get_indicators, store_indicators
from .redis_client import (
    close_redis,
    get_cache_stats,
    get_redis_client,
    init_redis,
    reset_cache_stats,
)
from .signal_cache import cache_signal, get_cached_signal, invalidate_signal, should_use_cache

__all__ = [
    # Lifecycle
    "init_redis",
    "close_redis",
    "get_redis_client",
    # Signal caching
    "cache_signal",
    "get_cached_signal",
    "invalidate_signal",
    "should_use_cache",
    # Alert cooldown
    "set_cooldown",
    "is_on_cooldown",
    "clear_cooldown",
    # Feature store
    "store_indicators",
    "get_indicators",
    # Statistics
    "get_cache_stats",
    "reset_cache_stats",
]
