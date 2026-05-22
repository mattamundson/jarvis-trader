"""
Watchlist management endpoints
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["watchlist"])

# Global references (injected from main.py)
db_manager = None
_data_manager = None


def inject_dependencies(dbm, data_manager=None):
    """Inject global dependencies from main.py"""
    global db_manager, _data_manager
    db_manager = dbm
    _data_manager = data_manager


class WatchlistAddRequest(BaseModel):
    """Add to watchlist request"""

    symbol: str


@router.get("/watchlist")
async def get_watchlist():
    """Return configured watchlists as ticker items with live prices"""
    all_symbols = list(settings.FUTURES_WATCHLIST) + list(settings.OPTIONS_WATCHLIST)
    prices: dict = {}
    try:
        if _data_manager is not None:
            batch = await _data_manager.get_batch_prices(all_symbols)
            for sym, price_data in batch.items():
                prices[sym] = {
                    "last_price": price_data.get("last_price"),
                    "change_pct": price_data.get("change_pct"),
                }
        else:
            for sym in all_symbols:
                prices[sym] = {"last_price": None, "change_pct": None}
    except Exception as e:
        logger.warning(f"Batch price fetch failed: {e}")
        for sym in all_symbols:
            prices.setdefault(sym, {"last_price": None, "change_pct": None})

    items = []
    names = {
        "MES": "Micro E-mini S&P 500",
        "MNQ": "Micro E-mini Nasdaq",
        "MCL": "Micro Crude Oil",
        "MGC": "Micro Gold",
        "MHG": "Micro Copper",
        "MYM": "Micro Dow",
        "M2K": "Micro Russell 2000",
    }
    for sym in settings.FUTURES_WATCHLIST:
        p = prices.get(sym, {})
        items.append(
            {
                "symbol": sym,
                "name": names.get(sym, sym),
                "type": "futures",
                "last_price": p.get("last_price"),
                "change_pct": p.get("change_pct"),
            }
        )
    for sym in settings.OPTIONS_WATCHLIST:
        p = prices.get(sym, {})
        items.append(
            {
                "symbol": sym,
                "name": sym,
                "type": "options",
                "last_price": p.get("last_price"),
                "change_pct": p.get("change_pct"),
            }
        )
    return items


@router.post("/watchlist")
async def add_to_watchlist(req: WatchlistAddRequest):
    """Add a symbol to the appropriate watchlist (futures or equities)."""
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(400, "symbol must not be empty")

    futures_symbols = {"MES", "MNQ", "MCL", "MGC", "MHG", "MYM", "M2K", "ES", "NQ", "CL", "GC"}
    is_futures = symbol in futures_symbols

    if is_futures:
        if symbol not in settings.FUTURES_WATCHLIST:
            settings.FUTURES_WATCHLIST = list(settings.FUTURES_WATCHLIST) + [symbol]
    else:
        if symbol not in settings.OPTIONS_WATCHLIST:
            settings.OPTIONS_WATCHLIST = list(settings.OPTIONS_WATCHLIST) + [symbol]

    return {"status": "added", "symbol": symbol, "type": "futures" if is_futures else "options"}


@router.get("/watchlist/scan")
async def scan_watchlist(symbols: str = "MES,MNQ,MCL"):
    """Run MTF analysis on watchlist symbols and return a consolidated signal summary."""
    from fastapi import HTTPException as _HTTPException

    try:
        from analytics.mtf_analyzer import analyze_mtf

        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            raise _HTTPException(status_code=400, detail="No symbols provided")

        results = []
        for sym in symbol_list[:5]:
            try:
                mtf_result = await analyze_mtf(sym, _data_manager)
                results.append(
                    {
                        "symbol": sym,
                        "recommendation": mtf_result.recommendation,
                        "alignment": mtf_result.alignment,
                        "timeframes": {
                            s.timeframe: {"stc_value": s.stc_value, "stc_signal": s.stc_signal}
                            for s in mtf_result.signals
                        },
                        "error": None,
                    }
                )
            except Exception as sym_err:
                results.append(
                    {
                        "symbol": sym,
                        "recommendation": "WAIT",
                        "alignment": "NEUTRAL",
                        "timeframes": {},
                        "error": str(sym_err),
                    }
                )

        buy_count = sum(1 for r in results if r["recommendation"] == "BUY")
        sell_count = sum(1 for r in results if r["recommendation"] == "SELL")
        market_bias = (
            "BULLISH"
            if buy_count > sell_count
            else "BEARISH" if sell_count > buy_count else "NEUTRAL"
        )

        return {
            "symbols": results,
            "market_bias": market_bias,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "wait_count": len(results) - buy_count - sell_count,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except _HTTPException:
        raise
    except Exception as e:
        logger.error(f"[WATCHLIST-SCAN] Failed: {e}")
        raise _HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str):
    """Remove a symbol from the watchlist (futures or equities)."""
    from fastapi import HTTPException as _HTTPException

    symbol = symbol.strip().upper()
    removed = False

    if symbol in settings.FUTURES_WATCHLIST:
        settings.FUTURES_WATCHLIST = [s for s in settings.FUTURES_WATCHLIST if s != symbol]
        removed = True
    elif symbol in settings.OPTIONS_WATCHLIST:
        settings.OPTIONS_WATCHLIST = [s for s in settings.OPTIONS_WATCHLIST if s != symbol]
        removed = True

    if not removed:
        raise _HTTPException(404, f"Symbol {symbol} not found in watchlist")

    return {"status": "removed", "symbol": symbol}
