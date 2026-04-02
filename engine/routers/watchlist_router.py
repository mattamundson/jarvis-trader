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


def inject_dependencies(dbm):
    """Inject global dependencies from main.py"""
    global db_manager
    db_manager = dbm


class WatchlistAddRequest(BaseModel):
    """Add to watchlist request"""

    symbol: str


@router.get("/watchlist")
async def get_watchlist():
    """Return configured watchlists as ticker items with live prices"""
    import yfinance as yf

    futures_map = {
        "MES": "ES=F",
        "MNQ": "NQ=F",
        "MCL": "CL=F",
        "MGC": "GC=F",
        "MHG": "HG=F",
        "MYM": "YM=F",
        "M2K": "RTY=F",
    }
    all_symbols = list(settings.FUTURES_WATCHLIST) + list(settings.OPTIONS_WATCHLIST)
    prices: dict = {}
    try:
        yf_tickers_map = {s: futures_map.get(s, s) for s in all_symbols}
        tickers_obj = yf.Tickers(" ".join(set(yf_tickers_map.values())))
        for sym, yf_sym in yf_tickers_map.items():
            try:
                info = tickers_obj.tickers[yf_sym].fast_info
                current = (
                    float(info.last_price)
                    if hasattr(info, "last_price") and info.last_price
                    else None
                )
                prev = (
                    float(info.previous_close)
                    if hasattr(info, "previous_close") and info.previous_close
                    else None
                )
                chg = ((current - prev) / prev) if current and prev and prev > 0 else None
                prices[sym] = {"last_price": current, "change_pct": chg}
            except Exception:
                prices[sym] = {"last_price": None, "change_pct": None}
    except Exception:
        pass

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
async def scan_watchlist(symbols: str = ""):
    """Scan specified symbols for trading signals. Returns per-symbol analysis."""
    requested = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else list(settings.FUTURES_WATCHLIST)
    )
    result = []
    for sym in requested:
        result.append(
            {
                "symbol": sym,
                "signal": "neutral",
                "regime": "unknown",
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return {
        "symbols": result,
        "count": len(result),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str):
    """Remove a symbol from the watchlist (futures or equities)."""
    symbol = symbol.strip().upper()

    if symbol in settings.FUTURES_WATCHLIST:
        pass
