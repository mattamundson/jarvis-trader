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


def inject_dependencies():
    """Inject dependencies from main.py"""
    pass


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

    # If FRED returned nothing useful (all None), enrich VIX from yfinance
    if not raw or raw.get("vix", {}) in (None, {}, {"value": None}):
        try:
            import yfinance as yf

            vix_df = yf.download("^VIX", period="2d", interval="1d", progress=False)
            if vix_df is not None and not vix_df.empty:
                # Flatten MultiIndex if needed
                if hasattr(vix_df.columns, "nlevels") and vix_df.columns.nlevels > 1:
                    vix_df.columns = vix_df.columns.get_level_values(0)
                vix_df.columns = [c.lower() for c in vix_df.columns]
                vix_live = float(vix_df["close"].iloc[-1])
                raw.setdefault("vix", {"value": vix_live, "unit": "index", "description": "CBOE Volatility Index (yfinance)"})
                logger.info("VIX fallback via yfinance: %.2f", vix_live)
        except Exception as yf_err:
            logger.warning("yfinance VIX fallback also failed: %s", yf_err)

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


# ── Backtest endpoint ──────────────────────────────────────────────────────────
