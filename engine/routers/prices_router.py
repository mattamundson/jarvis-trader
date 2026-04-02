"""
Market pricing endpoints with caching and rate limit handling.
"""

import logging
from functools import partial

from fastapi import APIRouter

from data.price_cache import PriceCache, retry_with_backoff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["prices", "market"])

# Global price cache (injected from main.py)
_price_cache: PriceCache = PriceCache()

FUTURES_MAP = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MCL": "CL=F",
    "MGC": "GC=F",
    "MHG": "HG=F",
    "MYM": "YM=F",
    "M2K": "RTY=F",
}


def inject_dependencies(cache: PriceCache):
    """Inject price cache from main.py"""
    global _price_cache
    _price_cache = cache


async def _fetch_price_from_yfinance(yf_ticker: str, original_symbol: str) -> dict:
    """
    Fetch single price from yfinance.
    Raises exception on error for retry_with_backoff to handle.
    """
    import yfinance as yf

    tickers = yf.Tickers(yf_ticker)
    info = tickers.tickers[yf_ticker].fast_info
    current = float(info.last_price) if hasattr(info, "last_price") and info.last_price else None
    prev = (
        float(info.previous_close)
        if hasattr(info, "previous_close") and info.previous_close
        else None
    )
    chg = ((current - prev) / prev) if current and prev and prev > 0 else None

    return {
        "symbol": original_symbol,
        "last_price": current,
        "prev_close": prev,
        "change_pct": chg,
        "yf_ticker": yf_ticker,
        "source": "yfinance",
    }


@router.get("/prices/snapshot")
async def get_price_snapshot(symbols: str = "SPY,QQQ,MES,MNQ"):
    """
    Get current prices and daily change % for comma-separated symbols.
    Futures micro contracts (MES, MNQ, MCL etc) are mapped to continuous contracts.
    Results are cached with 60-second TTL to handle Polygon rate limits.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    result = {}
    for original_symbol in symbol_list:
        yf_ticker = FUTURES_MAP.get(original_symbol, original_symbol)

        # Try cache first
        cached = await _price_cache.get(original_symbol)
        if cached:
            result[original_symbol] = cached
            continue

        # Cache miss — fetch with retry backoff using partial to bind loop vars
        try:
            fetch_fn = partial(_fetch_price_from_yfinance, yf_ticker, original_symbol)
            data = await retry_with_backoff(
                fetch_fn,
                original_symbol,
                _price_cache,
            )
            if data:
                result[original_symbol] = data
            else:
                result[original_symbol] = {
                    "symbol": original_symbol,
                    "last_price": None,
                    "prev_close": None,
                    "change_pct": None,
                    "error": "No data available",
                }
        except Exception as e:
            logger.error(f"Price fetch failed for {original_symbol}: {e}")
            result[original_symbol] = {
                "symbol": original_symbol,
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "error": str(e),
            }

    return result


# ── Earnings calendar awareness ──────────────────────────────────────────────────
