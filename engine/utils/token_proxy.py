"""
JARVIS TRADER — Token Proxy
=============================
In-process token optimizer inspired by github.com/rtk-ai/rtk (60-90% savings).

Scope vs. token_optimizer.py
----------------------------
token_optimizer.py handles Anthropic-specific primitives: prompt caching blocks,
Haiku routing, IC-based context pruning. It is called at prompt CONSTRUCTION time.

token_proxy.py handles CLIENT-SIDE optimizations that are independent of the
model provider: whitespace compression, in-process response caching, market data
payload trimming. It is called at prompt TRANSPORT time — wraps any LLM call.

The two are complementary. Both can run on the same prompt: optimizer first to
add cache_control and route the model, proxy second to compress transport bytes
and serve cached responses for repeated analyst calls.

Reference: https://x.com/seelffff/status/2042247428930248939
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["TokenProxy", "TokenProxyMetrics", "get_token_proxy"]


@dataclass
class TokenProxyMetrics:
    """Rolling counters for proxy effectiveness."""

    compressions: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    chars_original: int = 0
    chars_after_compression: int = 0
    context_trims: int = 0
    market_data_trims: int = 0
    evictions: int = 0

    @property
    def chars_saved(self) -> int:
        return self.chars_original - self.chars_after_compression

    @property
    def savings_pct(self) -> float:
        if self.chars_original <= 0:
            return 0.0
        return round(self.chars_saved / self.chars_original * 100.0, 2)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return round(self.cache_hits / total * 100.0, 2)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "compressions": self.compressions,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "chars_original": self.chars_original,
            "chars_after_compression": self.chars_after_compression,
            "chars_saved": self.chars_saved,
            "savings_pct": self.savings_pct,
            "cache_hit_rate": self.cache_hit_rate,
            "context_trims": self.context_trims,
            "market_data_trims": self.market_data_trims,
            "evictions": self.evictions,
        }


class TokenProxy:
    """
    In-process token optimizer with compression, caching, and trimming.

    Thread-safe — internal cache access is mutex-protected. Stateless outside
    the cache (compression/trimming are pure functions).
    """

    # Cache TTL — short enough that market data stays fresh, long enough to
    # absorb duplicate analyst calls during a single pipeline run (~2 minutes).
    CACHE_TTL_SECONDS = 300

    # Default hard limit on context block length when trimming.
    MAX_CONTEXT_CHARS = 8000

    # Cache size cap — prevents unbounded memory growth in long-running
    # pipelines. When exceeded, oldest entry (by insertion time) is evicted.
    MAX_CACHE_SIZE = 200

    def __init__(
        self,
        cache_ttl_seconds: Optional[int] = None,
        max_context_chars: Optional[int] = None,
        max_cache_size: Optional[int] = None,
    ):
        self.cache_ttl_seconds = cache_ttl_seconds or self.CACHE_TTL_SECONDS
        self.max_context_chars = max_context_chars or self.MAX_CONTEXT_CHARS
        self.max_cache_size = max_cache_size or self.MAX_CACHE_SIZE

        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.metrics = TokenProxyMetrics()

    # ------------------------------------------------------------------
    # Compression — pure function, no state
    # ------------------------------------------------------------------

    def compress_prompt(self, prompt: str) -> str:
        """
        Reduce prompt transport size without changing semantics.

        Techniques:
        - Collapse 3+ newlines to 2
        - Strip trailing whitespace from each line
        - Collapse 2+ interior spaces to 1 (but preserve leading indentation)
        """
        if not prompt:
            return prompt

        original_len = len(prompt)

        # Step 1: Collapse excess blank lines (3+ → 2).
        compressed = re.sub(r"\n{3,}", "\n\n", prompt)

        # Step 2: Strip trailing whitespace from every line.
        compressed = "\n".join(line.rstrip() for line in compressed.split("\n"))

        # Step 3: Collapse interior multiple spaces. Use a per-line regex so
        # leading indentation (code blocks, JSON) is preserved.
        def _collapse_interior(line: str) -> str:
            # Preserve the leading whitespace
            stripped = line.lstrip()
            lead = line[: len(line) - len(stripped)]
            return lead + re.sub(r"  +", " ", stripped)

        compressed = "\n".join(_collapse_interior(line) for line in compressed.split("\n"))

        self.metrics.compressions += 1
        self.metrics.chars_original += original_len
        self.metrics.chars_after_compression += len(compressed)

        if original_len - len(compressed) > 0 and logger.isEnabledFor(logging.DEBUG):
            saved = original_len - len(compressed)
            logger.debug(
                "TokenProxy compressed %d → %d (saved %d chars, %.1f%%)",
                original_len,
                len(compressed),
                saved,
                saved / max(1, original_len) * 100.0,
            )

        return compressed

    # ------------------------------------------------------------------
    # Context window trimming
    # ------------------------------------------------------------------

    def trim_context(self, context: str, max_chars: Optional[int] = None) -> str:
        """
        Truncate a long context payload while preserving the head and tail.

        The middle is replaced with a short placeholder noting how much was
        dropped. This is for situations where the first few and last few
        bars/lines are more informative than the middle.
        """
        if context is None:
            return context
        limit = max_chars or self.max_context_chars
        if len(context) <= limit:
            return context

        head_chars = limit // 2 - 40
        tail_chars = limit // 2 - 40
        dropped = len(context) - head_chars - tail_chars
        trimmed = (
            context[:head_chars]
            + f"\n\n[... {dropped} chars trimmed by TokenProxy ...]\n\n"
            + context[-tail_chars:]
        )
        self.metrics.context_trims += 1
        return trimmed

    def trim_market_data(
        self,
        bars: List[Any],
        keep_recent: int = 50,
    ) -> List[Any]:
        """
        Keep only the most recent N bars of market data for LLM context.

        LLMs reliably give the most weight to the last few bars. Passing 500
        bars when the decision hinges on the last 20 is pure waste.
        """
        if not isinstance(bars, list):
            return bars
        if len(bars) <= keep_recent:
            return bars
        self.metrics.market_data_trims += 1
        return bars[-keep_recent:]

    # ------------------------------------------------------------------
    # Response cache
    # ------------------------------------------------------------------

    @staticmethod
    def cache_key(prompt: str, model: str = "default", salt: str = "") -> str:
        """Deterministic cache key: sha256(model + prompt + salt)[:32]."""
        h = hashlib.sha256()
        h.update(model.encode("utf-8"))
        h.update(b"::")
        h.update((prompt or "").encode("utf-8"))
        if salt:
            h.update(b"::")
            h.update(salt.encode("utf-8"))
        return h.hexdigest()[:32]

    def get_cached(
        self,
        prompt: str,
        model: str = "default",
        salt: str = "",
    ) -> Optional[Any]:
        """
        Return a cached response if present and not expired. None otherwise.

        Increments cache_hits or cache_misses on every call so the metrics
        reflect real observed behavior.
        """
        key = self.cache_key(prompt, model, salt)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.metrics.cache_misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self.cache_ttl_seconds:
                # Expired — remove and count as miss.
                del self._cache[key]
                self.metrics.cache_misses += 1
                return None
            self.metrics.cache_hits += 1
            return value

    def set_cached(
        self,
        prompt: str,
        response: Any,
        model: str = "default",
        salt: str = "",
    ) -> None:
        """
        Store a response in the cache with the current timestamp.

        When the cache would exceed max_cache_size, the oldest entry (by
        insertion time) is evicted first.
        """
        key = self.cache_key(prompt, model, salt)
        with self._lock:
            if len(self._cache) >= self.max_cache_size and key not in self._cache:
                # Evict the oldest entry.
                oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
                self.metrics.evictions += 1
            self._cache[key] = (time.time(), response)

    # ------------------------------------------------------------------
    # One-shot optimize() — compress + cache lookup in one call
    # ------------------------------------------------------------------

    def optimize(
        self,
        prompt: str,
        model: str = "default",
        salt: str = "",
    ) -> Tuple[str, Optional[Any]]:
        """
        Apply compression and check the cache in one call.

        Returns:
            (compressed_prompt, cached_response_or_None)

        Typical call-site pattern:
            compressed, cached = proxy.optimize(prompt, model="claude-sonnet-4-6")
            if cached is not None:
                return cached
            response = await llm.call(... prompt=compressed ...)
            proxy.set_cached(compressed, response, model="claude-sonnet-4-6")
            return response
        """
        compressed = self.compress_prompt(prompt)
        cached = self.get_cached(compressed, model, salt)
        return compressed, cached

    # ------------------------------------------------------------------
    # Cache management helpers
    # ------------------------------------------------------------------

    def clear_cache(self) -> int:
        """Drop all cached responses. Returns count cleared."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
        return count

    def cache_size(self) -> int:
        """Current number of entries in cache."""
        with self._lock:
            return len(self._cache)

    def get_metrics(self) -> Dict[str, Any]:
        """Return proxy metrics as a plain dict (JSON-serializable)."""
        return self.metrics.as_dict()


# ---------------------------------------------------------------------------
# Module-level singleton — cheap for callers that don't want to thread state
# ---------------------------------------------------------------------------

_global_proxy: Optional[TokenProxy] = None
_global_lock = threading.Lock()


def get_token_proxy() -> TokenProxy:
    """
    Return the process-wide TokenProxy singleton.

    Thread-safe lazy init — first caller constructs, everyone else reuses.
    """
    global _global_proxy
    if _global_proxy is not None:
        return _global_proxy
    with _global_lock:
        if _global_proxy is None:
            _global_proxy = TokenProxy()
    return _global_proxy
