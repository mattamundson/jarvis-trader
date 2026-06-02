"""
Market data endpoints
"""

import logging
import time

from fastapi import APIRouter, HTTPException

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["market"])


@router.get("/position-sizing/calculate")
async def calculate_position_size_alias():
    """Top-level alias for position sizing calculation."""
    from utils.position_sizing import calculate_position_size

    result = calculate_position_size(
        symbol="MES",
        account_value=settings.INITIAL_CAPITAL,
        atr=15.0,
        risk_pct=0.01,
        atr_stop_multiplier=0.70,
        max_contracts=2,
    )
    return {
        "symbol": result.symbol,
        "contracts": result.contracts,
        "risk_per_trade": result.risk_per_trade,
        "stop_distance": result.stop_distance,
        "dollar_risk_per_contract": result.dollar_risk_per_contract,
        "account_value": result.account_value,
        "reasoning": result.reasoning,
    }

# Global references (injected from main.py)
_data_manager = None


def inject_dependencies(data_manager=None):
    """Inject dependencies from main.py"""
    global _data_manager
    if data_manager is not None:
        _data_manager = data_manager


@router.get("/market/earnings")
async def get_upcoming_earnings(days: int = 7):
    """Check for upcoming earnings near our watched symbols.

    Earnings calendar data is not currently available without yfinance.
    Returns an empty list — wire a Finnhub or Polygon earnings endpoint
    to populate this in a future iteration.
    """
    return {
        "upcoming_earnings": [],
        "count": 0,
        "days_lookahead": days,
        "note": "Earnings calendar unavailable — integrate Finnhub /calendar/earnings for live data",
        "source": "unavailable",
    }


@router.get("/market/session")
async def get_market_session():
    """Return current market session status (pre-market, regular, after-hours, closed)."""
    import zoneinfo
    from datetime import datetime

    eastern = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(tz=eastern)
    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour, minute = now.hour, now.minute
    time_val = hour * 60 + minute

    if weekday >= 5:  # Saturday or Sunday
        session = "closed"
        description = "Markets closed — weekend"
    elif time_val < 4 * 60:  # before 4:00 AM ET
        session = "closed"
        description = "Markets closed — overnight"
    elif time_val < 9 * 60 + 30:  # 4:00–9:30 AM ET
        session = "pre_market"
        description = "Pre-market session (4:00–9:30 AM ET)"
    elif time_val < 16 * 60:  # 9:30 AM–4:00 PM ET
        session = "regular"
        description = "Regular trading hours (9:30 AM–4:00 PM ET)"
    elif time_val < 20 * 60:  # 4:00–8:00 PM ET
        session = "after_hours"
        description = "After-hours session (4:00–8:00 PM ET)"
    else:
        session = "closed"
        description = "Markets closed — after hours"

    return {
        "session": session,
        "description": description,
        "timestamp": now.isoformat(),
        "is_open": session == "regular",
    }


@router.get("/market/data-source-status")
async def get_data_source_status(
    symbol: str = "MCL",
    timeframe: str = "1h",
    lookback_days: int = 30,
):
    """Probe the data fallback chain for a symbol and report which source served.

    Returns: which source won (ibkr|polygon|csv_cache|none), bar count, latency.
    Intended for operator dashboards to catch silent data-source failures
    (e.g. Polygon 2026-04-16 futures-blocklist, CSV cache staleness).
    """
    if _data_manager is None:
        raise HTTPException(
            status_code=503, detail="MarketDataManager not injected yet; engine starting"
        )

    start = time.time()
    try:
        df = await _data_manager.get_bars(
            symbol=symbol,
            timeframe=timeframe,
            lookback_days=lookback_days,
        )
    except Exception as exc:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "error",
            "bars": 0,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error": str(exc),
        }
    source = df.attrs.get("source", "unknown") if not df.empty else df.attrs.get("source", "none")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "bars": int(len(df)),
        "latency_ms": round((time.time() - start) * 1000, 1),
    }

@router.get("/prices/snapshot")
async def get_price_snapshot(symbols: str = "SPY,QQQ,MES,MNQ,MCL"):
    """
    Get current prices and daily change % for comma-separated symbols.
    Futures micro contracts (MES, MNQ, MCL etc) are mapped via data_manager.
    """
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    try:
        batch = await data_manager.get_batch_prices(symbol_list)
        result = {}
        for sym in symbol_list:
            price_dict = batch.get(sym, {})
            result[sym] = {
                "symbol": sym,
                "last_price": price_dict.get("last_price"),
                "prev_close": price_dict.get("prev_close"),
                "change_pct": price_dict.get("change_pct"),
                "source": price_dict.get("source"),
            }
        return result
    except Exception as e:
        raise HTTPException(500, f"Price fetch failed: {e}") from e


# ── Earnings calendar awareness ──────────────────────────────────────────────────


