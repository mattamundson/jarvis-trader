"""TTL-based in-memory cache for pre-fetched market data and indicators."""

import threading
import time
from typing import Any, Optional


class PrefetchCache:
    """
    Thread-safe in-memory TTL cache.
    Stores: market_data, technical_indicators, regime_states per symbol.
    Default TTL: 10 minutes (data freshness window).
    """

    DEFAULT_TTL_SECONDS = 600  # 10 minutes

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set a value with TTL."""
        expiry = time.monotonic() + (ttl or self._ttl)
        with self._lock:
            self._store[key] = (value, expiry)

    def get(self, key: str) -> Optional[Any]:
        """Get value if not expired. Returns None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() > expiry:
                del self._store[key]
                return None
            return value

    def has(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def invalidate(self, key: str) -> None:
        """Remove a key from cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            now = time.monotonic()
            valid = sum(1 for _, expiry in self._store.values() if expiry > now)
            return {
                "total_keys": len(self._store),
                "valid_keys": valid,
                "expired_keys": len(self._store) - valid,
                "ttl_seconds": self._ttl,
            }

    def keys_by_prefix(self, prefix: str) -> list[str]:
        """Return all valid keys starting with prefix."""
        with self._lock:
            now = time.monotonic()
            return [k for k, (_, exp) in self._store.items() if k.startswith(prefix) and exp > now]
