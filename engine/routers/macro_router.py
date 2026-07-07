"""
Macro economic data endpoints
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["macro"])

# Global references (injected from main.py)
_macro_cache = {}
_data_manager = None


def inject_dependencies(data_manager=None):
    """Inject dependencies from main.py"""
    global _data_manager
    _data_manager = data_manager


@router.get("/macro/snapshot")
async def get_macro_snapshot():
    """
    Current macro environment from FRED — flat snapshot for dashboard polling.

    Returns:
        {"vix": float, "fed_funds_rate": float, "ten_year_yield": float, "unemployment": float}

    Uses a 5-minute in-memory cache so 60s dashboard polling doesn't hammer FRED.
    The underlying FREDDataService already caches at 1h per series; this adds a
    dedicated short-TTL cache for the flattened response shape.
    """
    from data.fred_data import get_fred_service

    # 5-minute in-memory cache for the flattened snapshot
    now = datetime.now()
    cached = _macro_cache.get("snapshot")
    if cached and (now - cached["_ts"]).total_seconds() < 300:
        return {k: v for k, v in cached.items() if k != "_ts"}

    service = get_fred_service()
    try:
        raw = service.get_macro_snapshot()
    except Exception as e:
        logger.warning("get_macro_snapshot() raised unexpectedly: %s — building fallback", e)
        raw = {}

    # If FRED returned nothing useful (all None), enrich VIX from data_manager
    if not raw or raw.get("vix", {}) in (None, {}, {"value": None}):
        try:
            if _data_manager is not None:
                vix_result = await _data_manager.get_vix()
                vix_value = vix_result.get("value")
                if vix_value is not None:
                    raw.setdefault(
                        "vix",
                        {
                            "value": float(vix_value),
                            "unit": "index",
                            "description": f"CBOE Volatility Index ({vix_result.get('source', 'data_manager')})",
                        },
                    )
                    logger.info("VIX fallback via data_manager: %.2f", float(vix_value))
        except Exception as dm_err:
            logger.warning("data_manager VIX fallback also failed: %s", dm_err)

    # The FREDDataService returns nested dicts: {"vix": {"value": 27.4, ...}, ...}
    # Flatten to the shape the dashboard WatchlistBar expects.
    def _val(key: str):
        entry = raw.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry.get("value")
        try:
            return float(entry)
        except (TypeError, ValueError):
            return None

    flat = {
        "vix": _val("vix"),
        "fed_funds_rate": _val("fed_funds_rate"),
        "ten_year_yield": _val("ten_year_yield"),
        "unemployment": _val("unemployment"),
        "timestamp": raw.get("timestamp", now.isoformat()),
    }

    # Classify VIX into a regime band so the command-center / options tiles render
    # a real regime instead of "—". Same thresholds as the options strategy
    # executor (LOW <15, NORMAL 15-20, HIGH 20-30, EXTREME >=30).
    try:
        from options.strategy_executor import classify_vix_regime

        flat["vix_regime"] = (
            classify_vix_regime(flat["vix"]).value if flat["vix"] is not None else None
        )
    except Exception as exc:  # never let regime enrichment break the snapshot
        logger.debug("vix_regime classification failed: %s", exc)
        flat["vix_regime"] = None

    # Store in cache with sentinel timestamp
    _macro_cache["snapshot"] = {**flat, "_ts": now}

    return flat


@router.get("/macro/series/{series_id}")
async def get_macro_series(series_id: str, periods: int = 24):
    """Get historical data for a FRED series (e.g. FEDFUNDS, GS10, VIXCLS)"""
    from data.fred_data import get_fred_service

    service = get_fred_service()
    history = service.get_series_history(series_id.upper(), periods)
    if not history:
        raise HTTPException(404, f"FRED series {series_id} not found or unavailable")
    return {"series_id": series_id.upper(), "data": history, "count": len(history)}


@router.get("/macro/regime")
async def get_macro_regime():
    """Market-wide macro trend regime (RISK_ON/RISK_OFF/NEUTRAL/UNKNOWN).

    Derived from the two real trend edges of the X-bookmark scan applied to SPY as
    an S&P proxy: weekly Supertrend(ATR10, x3) + monthly 12mo-SMA momentum. ADVISORY
    only — this never routes capital; the futures pipeline reads it only when the
    ENABLE_MACRO_TREND_BIAS feature flag is on. 5-min cache over macro_regime's own
    6h compute cache.
    """
    now = datetime.now()
    cached = _macro_cache.get("regime")
    if cached and (now - cached["_ts"]).total_seconds() < 300:
        return {k: v for k, v in cached.items() if k != "_ts"}

    try:
        from backtest.macro_regime import compute_macro_regime

        result = compute_macro_regime()
    except Exception as e:
        logger.warning("compute_macro_regime failed: %s", e)
        raise HTTPException(500, f"macro regime computation failed: {e}") from e

    _macro_cache["regime"] = {**result, "_ts": now}
    return result


# ── Backtest endpoint ──────────────────────────────────────────────────────────
