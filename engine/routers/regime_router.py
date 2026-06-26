"""Intraday market-regime endpoint.

GET /regime/intraday?symbol=SPY — composite regime score, per-timeframe scores,
indicator breakdown, and score history, computed from OHLCV bars by the pure
analytics module (no LLM). Powers the dashboard Intraday Market Regime view.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from analytics.intraday_regime import build_regime_snapshot
from analytics.options_flow import get_options_flow

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

    # Best-effort dealer-GEX; runs off the event loop and returns None when no
    # options source is wired (current paper-phase state).
    options_flow = None
    if not futures:
        try:
            options_flow = await asyncio.to_thread(get_options_flow, sym)
        except Exception as e:  # noqa: BLE001 — options flow is never fatal
            logger.warning("[REGIME] %s options flow unavailable: %s", sym, e)

    try:
        return build_regime_snapshot(sym, bars_by_tf, options_flow=options_flow)
    except Exception as e:
        logger.error("[REGIME] snapshot failed for %s: %s", sym, e)
        raise HTTPException(500, f"Regime snapshot failed: {e}") from e


def _close_series(df):
    """Extract a lowercase 'close' Series from a bars DataFrame, or None."""
    if df is None or df.empty:
        return None
    cols = {c.lower(): c for c in df.columns}
    if "close" not in cols:
        return None
    return df[cols["close"]].astype(float)


@router.get("/vix-percentile")
async def get_vix_percentile_regime(
    lookback: int = 252,
    momentum_window: int = 63,
    price_symbol: str = "SPY",
) -> dict:
    """Percentile-based VIX regime snapshot (additive second lens).

    Classifies the current VIX into Crisis/HighVol/MidVol/LowVol by trailing
    percentile and overlays Bull/Neutral/Bear momentum from ``price_symbol``.
    Distinct from /regime/intraday (per-symbol composite) and from the fixed
    VIX>35 classifier used by gate v2 — this is a research/monitoring view.
    """
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")
    if lookback < 2:
        raise HTTPException(422, "lookback must be >= 2")

    import pandas as pd

    from backtest.vix_percentile_regime import regime_snapshot

    # Calendar buffer so ~lookback+momentum_window *trading* days survive weekends/holidays.
    days = int((lookback + momentum_window) * 1.6) + 10
    psym = price_symbol.strip().upper() or "SPY"

    try:
        vix_df = await data_manager.get_bars("VIX", lookback_days=days, timeframe="1d")
        price_df = await data_manager.get_bars(psym, lookback_days=days, timeframe="1d")
    except Exception as e:  # noqa: BLE001 — upstream data failure is a 502, not a 500
        logger.error("[REGIME] vix-percentile bar fetch failed: %s", e)
        raise HTTPException(502, f"VIX/price bar fetch failed: {e}") from e

    vix_close = _close_series(vix_df)
    if vix_close is None or len(vix_close) < 2:
        raise HTTPException(404, "Insufficient VIX history for percentile classification")

    price_close = _close_series(price_df)
    if price_close is None:
        # No price source -> momentum degrades to Neutral, tier still computable.
        logger.warning("[REGIME] %s price bars unavailable; momentum -> Neutral", psym)
        price_close = pd.Series(float("nan"), index=vix_close.index)
    else:
        # Align to the common index so classify_latest sees matched series.
        joined = pd.concat([vix_close, price_close], axis=1, join="inner").dropna(how="all")
        if joined.empty:
            price_close = pd.Series(float("nan"), index=vix_close.index)
        else:
            vix_close = joined.iloc[:, 0]
            price_close = joined.iloc[:, 1].ffill()

    try:
        snap = regime_snapshot(
            vix_close, price_close, lookback=lookback, momentum_window=momentum_window
        )
    except Exception as e:
        logger.error("[REGIME] vix-percentile classify failed: %s", e)
        raise HTTPException(500, f"VIX percentile classification failed: {e}") from e

    snap["price_symbol"] = psym
    snap["n_vix_bars"] = int(len(vix_close))
    return snap
