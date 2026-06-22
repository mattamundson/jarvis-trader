"""VIX/VIX3M term-structure regime overlay for JARVIS TRADER.

The VIX *level* overlay (analytics/vix_overlay.py) sizes by how high fear is. This
adds the orthogonal *term-structure* dimension: the slope between the 30-day VIX and
the 90-day VIX3M. In CONTANGO (VIX3M > VIX) the curve is calm/normal; in BACKWARDATION
(VIX > VIX3M) the front is bid above the back -- the classic stress signature that
leads sustained volatility regimes.

This signal was validated in a standalone research prototype (~/Code/options-vrp) as
the one durable, transferable asset across multiple vol strategies: gating short-vol by
contango/backwardation consistently lifted return AND cut the tail. The classify logic
here is ported verbatim from that prototype (vrp_signal.classify_term_structure).

IMPORTANT -- this is a NEW HYPOTHESIS for directional micro-futures: "term-structure
improves directional-futures risk-adjusted return" is NOT yet validated (the prototype
proved it for *short-vol* strategies). It ships OFF by default (settings.TS_OVERLAY_
ENABLED) and must clear an A/B gate-v2 backtest (backtest/run_term_structure_overlay_ab.py)
before any live enable.

Units: VIX and VIX3M are in points (e.g. 18.5), as delivered by FRED VIXCLS / VXVCLS.
slope = VIX3M - VIX; the flat dead-band is in the same points (default 0.5 pts, the
options-vrp 0.005-decimal default rescaled to points).
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level 15-minute cache (mirrors analytics.vix_overlay._vix_cache)
_ts_cache: dict = {}
_CACHE_TTL = 900  # seconds


class Regime(str, Enum):
    """VIX term-structure regime (ported verbatim from options-vrp.vrp_signal)."""

    CONTANGO = "CONTANGO"            # VIX3M > VIX -- calm/normal (favorable)
    FLAT = "FLAT"                    # within the dead-band
    BACKWARDATION = "BACKWARDATION"  # VIX > VIX3M -- stress/inverted (stand aside)


def classify_term_structure(front_iv: float, back_iv: float,
                            flat_band: float = 0.5) -> tuple[Regime, float]:
    """Classify the VIX term structure. slope = back - front (same units in/out).

    front_iv = VIX (30d), back_iv = VIX3M (90d), both in points. |slope| within
    flat_band => FLAT. Logic is bit-for-bit the options-vrp validated classifier;
    only the default flat_band is rescaled from 0.005 decimal to 0.5 points.
    """
    slope = float(back_iv) - float(front_iv)
    if slope > flat_band:
        return Regime.CONTANGO, slope
    if slope < -flat_band:
        return Regime.BACKWARDATION, slope
    return Regime.FLAT, slope


def regime_multiplier(
    regime: Regime,
    contango_mult: float = 1.0,
    flat_mult: float = 1.0,
    backwardation_mult: float = 0.5,
) -> float:
    """Map a regime to a position-size multiplier (0..1)."""
    if regime == Regime.CONTANGO:
        return contango_mult
    if regime == Regime.BACKWARDATION:
        return backwardation_mult
    return flat_mult


def apply_term_structure_scaling(
    contracts: int,
    front_iv: float | None,
    back_iv: float | None,
    flat_band: float = 0.5,
    contango_mult: float = 1.0,
    flat_mult: float = 1.0,
    backwardation_mult: float = 0.5,
    standaside_on_backwardation: bool = False,
    max_contracts: int = 2,
) -> tuple[int, str]:
    """VIX term-structure position-size overlay (pure function; gate it upstream).

    Rescales an already-computed contract count by the term-structure regime:
    CONTANGO (calm) keeps size, BACKWARDATION (stress) shrinks it (or stands aside).
    The live-sizer analogue of the regime filter validated in ~/Code/options-vrp.
    Risk overlay only -- it never *creates* a trade. It floors at 1 (an approved
    trade is never zeroed) UNLESS ``standaside_on_backwardation`` is set, in which
    case BACKWARDATION returns 0 to signal HOLD.

    Caller owns the enable gate (``settings.TS_OVERLAY_ENABLED``); this is a no-op
    passthrough whenever it lacks the inputs to classify.

    Args:
        contracts: base contract count from the upstream sizing chain.
        front_iv: VIX (30d) in points. None/<=0 => passthrough.
        back_iv: VIX3M (90d) in points. None/<=0 => passthrough.
        flat_band: dead-band in points for the FLAT regime.
        contango_mult / flat_mult / backwardation_mult: per-regime multipliers.
        standaside_on_backwardation: if True, BACKWARDATION returns 0 (HOLD).
        max_contracts: hard ceiling; the scaled result is clamped to it.

    Returns:
        (scaled_contracts, reasoning) -- ``scaled_contracts == contracts`` on any
        passthrough path; 0 only on an explicit BACKWARDATION stand-aside.
    """
    if contracts <= 0:
        return contracts, "no base contracts; term-structure passthrough"
    if front_iv is None or back_iv is None or front_iv <= 0 or back_iv <= 0:
        return contracts, "VIX/VIX3M unavailable; term-structure passthrough"

    regime, slope = classify_term_structure(float(front_iv), float(back_iv), flat_band)

    if regime == Regime.BACKWARDATION and standaside_on_backwardation:
        return 0, (f"term-structure: BACKWARDATION (VIX {front_iv:.2f} > VIX3M {back_iv:.2f}, "
                   f"slope {slope:+.2f}); stand aside -> HOLD")

    mult = regime_multiplier(regime, contango_mult, flat_mult, backwardation_mult)
    scaled = max(1, min(int(round(contracts * mult)), max_contracts))
    reasoning = (
        f"term-structure: {regime.value} (VIX {front_iv:.2f} vs VIX3M {back_iv:.2f}, "
        f"slope {slope:+.2f}) => x{mult:.2f}; contracts {contracts} -> {scaled} "
        f"[clamp 1..{max_contracts}]"
    )
    return scaled, reasoning


# ---------------------------------------------------------------------------
# Optional live read surface (analytics/health). Mirrors vix_overlay's cache.
# ---------------------------------------------------------------------------
@dataclass
class VIXTermState:
    """Current VIX/VIX3M reading and derived term-structure regime."""

    vix: float
    vix3m: float
    slope: float
    regime: str
    timestamp: float
    source: str = "stub"
    error: Optional[str] = None


async def fetch_term_structure_async(data_manager=None, flat_band: float = 0.5) -> VIXTermState:
    """Async VIX+VIX3M fetch via MarketDataManager with a 15-min module cache.

    Returns a stub (VIX 18 / VIX3M 19 / CONTANGO) when no data_manager is given or a
    fetch fails -- this is a read/health surface, not the live sizing path (the live
    sizer reads VIX/VIX3M from the fundamental report). Gives market_data.get_vix3m()
    a consumer and backs a future /analytics term-structure endpoint.
    """
    now = time.time()
    cached: Optional[VIXTermState] = _ts_cache.get("data")
    if cached is not None and (now - _ts_cache.get("fetched_at", 0)) < _CACHE_TTL:
        return cached

    if data_manager is not None:
        try:
            vix_d = await data_manager.get_vix()
            v3_d = await data_manager.get_vix3m()
            vix = vix_d.get("value") if isinstance(vix_d, dict) else None
            v3 = v3_d.get("value") if isinstance(v3_d, dict) else None
            if vix and v3 and vix > 0 and v3 > 0:
                regime, slope = classify_term_structure(float(vix), float(v3), flat_band)
                state = VIXTermState(float(vix), float(v3), slope, regime.value, now, "live")
                _ts_cache["data"], _ts_cache["fetched_at"] = state, now
                return state
        except Exception as e:  # noqa: BLE001 -- health surface, never raise
            logger.debug("[TermStructure] fetch failed (non-fatal): %s", e)
            regime, slope = classify_term_structure(18.0, 19.0, flat_band)
            return VIXTermState(18.0, 19.0, slope, regime.value, now, "error_fallback", str(e))

    regime, slope = classify_term_structure(18.0, 19.0, flat_band)
    return VIXTermState(18.0, 19.0, slope, regime.value, now, "stub")


__all__ = [
    "Regime",
    "classify_term_structure",
    "regime_multiplier",
    "apply_term_structure_scaling",
    "VIXTermState",
    "fetch_term_structure_async",
]
