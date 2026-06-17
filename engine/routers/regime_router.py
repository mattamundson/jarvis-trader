"""Intraday market-regime endpoint.

GET /regime/intraday?symbol=SPY — composite regime score, per-timeframe scores,
indicator breakdown, and score history, computed from OHLCV bars by the pure
analytics module (no LLM). Powers the dashboard Intraday Market Regime view.
"""

import logging

from fastapi import APIRouter, HTTPException

from analytics.intraday_regime import build_regime_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regime", tags=["regime"])

# Injected from main.py
data_manager = None

# Timeframe -> lookback days. 5m needs less history than 1h to fill the window.
_TIMEFRAME_LOOKBACK = {"5m": 5, "15m": 10, "1h": 30}


def inject_dependencies(dm) -> None:
    """Inject the shared data manager from main.py."""
    global data_manager
    data_manager = dm


@router.get("/intraday")
async def get_intraday_regime(symbol: str = "SPY", futures: bool = False) -> dict:
    """Composite intraday regime snapshot for a symbol across 5m/15m/1h."""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(422, "symbol is required")

    bars_by_tf: dict = {}
    for tf, days in _TIMEFRAME_LOOKBACK.items():
        try:
            df = await data_manager.get_bars(
                sym, lookback_days=days, timeframe=tf, is_futures=futures
            )
            if df is not None and not df.empty:
                bars_by_tf[tf] = df
        except Exception as e:  # noqa: BLE001 — one bad timeframe shouldn't 500 the page
            logger.warning("[REGIME] %s %s bars unavailable: %s", sym, tf, e)

    if not bars_by_tf:
        raise HTTPException(404, f"No bar data available for {sym}")

    try:
        return build_regime_snapshot(sym, bars_by_tf)
    except Exception as e:
        logger.error("[REGIME] snapshot failed for %s: %s", sym, e)
        raise HTTPException(500, f"Regime snapshot failed: {e}") from e
