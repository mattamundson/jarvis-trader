"""
Market pricing endpoints with caching and rate limit handling.
"""

import asyncio
import logging
import time

from fastapi import APIRouter

from data.price_cache import PriceCache
from data.provenance import DEFAULT_STALE_AFTER_S, derive_is_live

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["prices", "market"])

# Global references (injected from main.py)
_price_cache: PriceCache = PriceCache()
_data_manager = None


def inject_dependencies(cache: PriceCache, data_manager=None):
    """Inject price cache and data manager from main.py"""
    global _price_cache, _data_manager
    _price_cache = cache
    _data_manager = data_manager


@router.get("/prices/snapshot")
async def get_price_snapshot(symbols: str = "SPY,QQQ,MES,MNQ,MCL"):
    """
    Get current prices and daily change % for comma-separated symbols.
    Futures micro contracts (MES, MNQ, MCL etc) are mapped to continuous contracts.
    Results are cached with 60-second TTL to handle Polygon rate limits.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    result = {}

    async def _fetch_one(original_symbol: str) -> None:
        # Try cache first
        cached = await _price_cache.get(original_symbol)
        if cached:
            result[original_symbol] = cached
            return

        # Cache miss — fetch via data_manager
        try:
            if _data_manager is not None:
                price_data = await _data_manager.get_current_price(original_symbol)
                source = price_data.get("source", "data_manager")
                as_of = time.time()
                # Provenance is DERIVED, never hardcoded: a cached/delayed tier
                # (csv_cache, polygon REST) is never live; an IBKR value is only
                # live when its data leg is connected. Lets the dashboard render
                # an honest LIVE/STATIC/STALE badge instead of "fetched recently".
                ibkr_connected = bool(
                    getattr(_data_manager, "ibkr", None)
                    and _data_manager.ibkr.is_connected
                )
                data = {
                    "symbol": original_symbol,
                    "last_price": price_data.get("last_price"),
                    "prev_close": price_data.get("prev_close"),
                    "change_pct": price_data.get("change_pct"),
                    "source": source,
                    "as_of": as_of,
                    "is_live": derive_is_live(
                        source,
                        as_of,
                        DEFAULT_STALE_AFTER_S,
                        ibkr_data_connected=ibkr_connected,
                        now=as_of,
                    ),
                    "stale_after_s": DEFAULT_STALE_AFTER_S,
                }
            else:
                data = None

            if data and data.get("last_price"):
                await _price_cache.set(original_symbol, data)
                result[original_symbol] = data
            else:
                result[original_symbol] = {
                    "symbol": original_symbol,
                    "last_price": None,
                    "prev_close": None,
                    "change_pct": None,
                    "source": "unavailable",
                    "as_of": None,
                    "is_live": False,
                    "stale_after_s": DEFAULT_STALE_AFTER_S,
                    "error": "No data available",
                }
        except Exception as e:
            logger.error(f"Price fetch failed for {original_symbol}: {e}")
            result[original_symbol] = {
                "symbol": original_symbol,
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "unavailable",
                "as_of": None,
                "is_live": False,
                "stale_after_s": DEFAULT_STALE_AFTER_S,
                "error": str(e),
            }

    # 2026-08-17: fetch cache-missed symbols CONCURRENTLY. The previous
    # sequential loop serialized N Polygon/IBKR round-trips — a 6-symbol cold
    # fetch took ~9s and froze /pipeline/actionable (the recommendation card)
    # on every 60s price-cache expiry. gather() keeps total latency ≈
    # single-symbol latency.
    await asyncio.gather(*(_fetch_one(s) for s in symbol_list))

    return result


# ── Earnings calendar awareness ──────────────────────────────────────────────────
