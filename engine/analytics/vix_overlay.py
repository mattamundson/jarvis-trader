"""VIX-based market regime overlay for JARVIS TRADER.

Fetches live ^VIX from MarketDataManager with a 15-minute module-level
cache. Falls back to stub value (18.0 / NORMAL) if the network call fails.

VIX Regime Map:
  VIX < 12   -> CALM     -- Full position sizing, all signals pass
  VIX 12-20  -> NORMAL   -- Full position sizing, all signals pass
  VIX 20-30  -> CAUTION  -- 75% position sizing, only strong signals
  VIX 30-40  -> ELEVATED -- 50% position sizing, only strong signals
  VIX >= 40  -> EXTREME  -- Trading paused (kill signals)
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level 15-minute cache
# ---------------------------------------------------------------------------
_vix_cache: dict = {}
_CACHE_TTL = 900  # seconds


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------
@dataclass
class VIXState:
    """Current VIX reading and derived regime."""

    vix_value: float
    regime: str  # CALM / NORMAL / CAUTION / ELEVATED / EXTREME
    classification: str  # Same as regime (alias for API consumers)
    position_size_pct: float  # 0.0-1.0 -- multiply raw contracts by this
    trading_allowed: bool
    timestamp: float  # Unix epoch (time.time())
    source: str = "stub"  # "live" | "cache" | "stub" | "error_fallback"
    error: Optional[str] = None

    @property
    def as_datetime(self) -> datetime:
        """Timestamp as UTC datetime (for legacy consumers)."""
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    @property
    def description(self) -> str:
        descriptions = {
            "CALM": "VIX below 12 -- low volatility, full position sizing",
            "NORMAL": "VIX 12-20 -- normal conditions",
            "CAUTION": "VIX 20-30 -- elevated vol, reduce size to 75%",
            "ELEVATED": "VIX 30-40 -- high volatility, reduce size to 50%",
            "EXTREME": "VIX above 40 -- extreme fear, trading paused",
        }
        return descriptions.get(self.regime, "Unknown")


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def classify_vix(vix_value: float) -> tuple:
    """
    Classify a VIX reading into a regime.
    Returns: (regime: str, position_size_pct: float, trading_allowed: bool)
    """
    if vix_value < 12:
        return "CALM", 1.0, True
    elif vix_value < 20:
        return "NORMAL", 1.0, True
    elif vix_value < 30:
        return "CAUTION", 0.75, True
    elif vix_value < 40:
        return "ELEVATED", 0.50, True
    else:
        return "EXTREME", 0.0, False


# ---------------------------------------------------------------------------
# Live fetch with cache
# ---------------------------------------------------------------------------
def fetch_vix() -> VIXState:
    """Return cached VIX state or a stub (18.0 / NORMAL).

    Synchronous callers use this; it only returns a live value when the async
    fetch_vix_async() has previously populated the module-level cache.
    """
    now = time.time()

    cached: Optional[VIXState] = _vix_cache.get("data")
    if cached is not None and (now - _vix_cache.get("fetched_at", 0)) < _CACHE_TTL:
        logger.debug(
            "[VIX] Returning cached value %.2f (%s)",
            cached.vix_value,
            cached.regime,
        )
        return VIXState(
            vix_value=cached.vix_value,
            regime=cached.regime,
            classification=cached.regime,
            position_size_pct=cached.position_size_pct,
            trading_allowed=cached.trading_allowed,
            timestamp=cached.timestamp,
            source="cache",
        )

    # No warm cache — return stub rather than blocking on a sync network call
    logger.debug("[VIX] No cache hit — returning stub 18.0/NORMAL (call fetch_vix_async first)")
    return VIXState(
        vix_value=18.0,
        regime="NORMAL",
        classification="NORMAL",
        position_size_pct=1.0,
        trading_allowed=True,
        timestamp=now,
        source="stub",
    )


async def fetch_vix_async(data_manager=None) -> VIXState:
    """Async VIX fetch via MarketDataManager with 15-min module-level cache.

    Flow:
      1. Return cached VIXState if fetched within the last 15 minutes.
      2. Try data_manager.get_vix() if data_manager is provided.
      3. On any failure, return a stub VIXState (value=18.0, NORMAL) and log.
    """
    now = time.time()

    cached: Optional[VIXState] = _vix_cache.get("data")
    if cached is not None and (now - _vix_cache.get("fetched_at", 0)) < _CACHE_TTL:
        logger.debug(
            "[VIX] Returning cached value %.2f (%s)",
            cached.vix_value,
            cached.regime,
        )
        return VIXState(
            vix_value=cached.vix_value,
            regime=cached.regime,
            classification=cached.regime,
            position_size_pct=cached.position_size_pct,
            trading_allowed=cached.trading_allowed,
            timestamp=cached.timestamp,
            source="cache",
        )

    if data_manager is None:
        return VIXState(
            vix_value=18.0,
            regime="NORMAL",
            classification="NORMAL",
            position_size_pct=1.0,
            trading_allowed=True,
            timestamp=now,
            source="stub",
        )

    try:
        vix_result = await data_manager.get_vix()
        vix_value = vix_result.get("value")
        if vix_value is None:
            raise ValueError("data_manager.get_vix() returned no value")

        vix_value = round(float(vix_value), 2)
        regime, position_size_pct, trading_allowed = classify_vix(vix_value)
        source = vix_result.get("source", "data_manager")

        state = VIXState(
            vix_value=vix_value,
            regime=regime,
            classification=regime,
            position_size_pct=position_size_pct,
            trading_allowed=trading_allowed,
            timestamp=now,
            source=source,
        )

        _vix_cache["data"] = state
        _vix_cache["fetched_at"] = now

        logger.info(
            "[VIX] Live fetch OK: %.2f -> %s (pos_size=%.0f%%, source=%s)",
            vix_value,
            regime,
            position_size_pct * 100,
            source,
        )
        return state

    except Exception as exc:
        error_msg = str(exc)[:120]
        logger.warning("[VIX] Live fetch failed -- using stub 18.0/NORMAL. Error: %s", error_msg)
        return VIXState(
            vix_value=18.0,
            regime="NORMAL",
            classification="NORMAL",
            position_size_pct=1.0,
            trading_allowed=True,
            timestamp=now,
            source="error_fallback",
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# VIXOverlay class -- preserves existing interface used by main.py
# ---------------------------------------------------------------------------
class VIXOverlay:
    """VIX-based regime overlay for trade signal filtering.

    Fetches live ^VIX via MarketDataManager (15-min cached). Falls back to
    stub on any network or data error so the rest of the system is never blocked.

    Usage:
        overlay = VIXOverlay(data_manager=data_manager)
        state = await overlay.get_current_state_async()  # preferred (async callers)
        state = overlay.get_current_state()              # sync callers (uses cache/stub)

        if not state.trading_allowed:
            return "HOLD"  # VIX >= 40, EXTREME regime

        adjusted_contracts = floor(raw_contracts * state.position_size_pct)
    """

    def __init__(self, ib_gateway=None, data_manager=None):
        self.ib_gateway = ib_gateway
        self.data_manager = data_manager
        logger.info("[VIXOverlay] Initialized -- MarketDataManager feed with 15-min cache")

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------
    def get_current_state(self) -> VIXState:
        """Get current VIX regime (sync). Returns cached value or stub.
        Call get_current_state_async() to refresh the cache from data_manager.
        Used by /analytics/regime in main.py.
        """
        return fetch_vix()

    async def get_current_state_async(self) -> VIXState:
        """Get current VIX regime (async). Refreshes cache via data_manager."""
        return await fetch_vix_async(self.data_manager)

    def get_state(self) -> VIXState:
        """Alias for get_current_state() -- used by sync callers."""
        return fetch_vix()

    async def get_state_async(self) -> VIXState:
        """Alias for get_current_state_async() -- used by async callers."""
        return await fetch_vix_async(self.data_manager)

    # ------------------------------------------------------------------
    # Trade filtering helpers (preserve existing interface)
    # ------------------------------------------------------------------
    def should_allow_trade(self, signal: str) -> tuple:
        """Check if a LONG/SHORT signal should be allowed given current VIX.

        Returns: (allowed: bool, reason: str)
        """
        state = self.get_current_state()
        if not state.trading_allowed:
            return False, f"VIX {state.vix_value:.1f} -- EXTREME regime, trading paused"
        return True, f"VIX {state.vix_value:.1f} ({state.regime}) -- trading allowed"

    def adjust_position_size(self, raw_contracts: int) -> int:
        """Adjust position size based on VIX regime.

        Returns adjusted contract count (minimum 1 if trading allowed, 0 if not).
        """
        state = self.get_current_state()
        if not state.trading_allowed:
            return 0
        return max(1, int(raw_contracts * state.position_size_pct))

    def get_trade_filter(self) -> str:
        """PASS for calm/normal, REDUCE for caution, BLOCK for elevated/extreme."""
        state = self.get_current_state()
        if state.regime in ("CALM", "NORMAL"):
            return "pass"
        elif state.regime == "CAUTION":
            return "reduce"
        else:
            return "block"

    # ------------------------------------------------------------------
    # Health check (preserve existing interface)
    # ------------------------------------------------------------------
    def health_check(self) -> dict:
        state = self.get_current_state()
        return {
            "enabled": True,
            "mode": state.source,
            "current_vix": state.vix_value,
            "regime": state.regime,
            "classification": state.classification,
            "position_size_pct": state.position_size_pct,
            "trading_allowed": state.trading_allowed,
            "source": state.source,
            "error": state.error,
            "cache_ttl_seconds": _CACHE_TTL,
        }
