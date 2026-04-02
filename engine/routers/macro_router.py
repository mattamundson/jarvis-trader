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
        raise HTTPException(500, f"FRED data unavailable: {e}") from e

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
