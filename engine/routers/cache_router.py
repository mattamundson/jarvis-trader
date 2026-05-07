"""
Cache management endpoints for JARVIS TRADER.

Provides manual invalidation of the 30-minute signal cache
without requiring an engine restart.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from cache import get_cache_stats
from cache.signal_cache import invalidate_all, invalidate_signal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cache", tags=["cache"])

# Known symbols — used to enumerate all cached keys for bulk clear
_KNOWN_SYMBOLS = ["MCL", "MNQ", "MES", "ES", "NQ", "CL", "GC", "SI", "ZC", "ZS"]


class InvalidateRequest(BaseModel):
    symbol: Optional[str] = None


@router.post("/invalidate")
async def invalidate_cache(body: InvalidateRequest = None):
    """
    Clear signal cache.

    - No body / body without symbol → clears ALL signals (Redis flushdb).
    - Body with {"symbol": "MCL"} → clears only that symbol.

    Returns {"cleared": [...], "count": N}
    """
    if body and body.symbol:
        symbol = body.symbol.upper()
        await invalidate_signal(symbol)
        logger.info(f"Cache invalidated for {symbol} via API")
        return {"cleared": [symbol], "count": 1}

    # Flush all signal keys
    await invalidate_all()
    logger.info("Full signal cache invalidated via API")
    return {"cleared": _KNOWN_SYMBOLS, "count": len(_KNOWN_SYMBOLS)}


@router.post("/invalidate/{symbol}")
async def invalidate_cache_symbol(symbol: str):
    """
    Clear signal cache for a single symbol.

    Returns {"cleared": ["MCL"], "count": 1}
    """
    symbol = symbol.upper()
    await invalidate_signal(symbol)
    logger.info(f"Cache invalidated for {symbol} via API")
    return {"cleared": [symbol], "count": 1}


@router.get("/stats")
async def cache_stats():
    """Return current cache hit/miss statistics."""
    return get_cache_stats()
