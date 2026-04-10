"""
TradingView Bridge API Routes
==============================
Exposes live JARVIS Pine indicator data (STC, Composite, Regime, IB, Corey,
etc.) from TradingView Desktop via the TVIndicatorBridge.

Routes:
  GET  /tv/snapshot?symbol=MES   — Full TVIndicatorSnapshot as JSON
  GET  /tv/health                — Bridge availability check
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from data.tv_indicator_bridge import get_tv_bridge

logger = logging.getLogger("jarvis_trader.routers.tradingview")

router = APIRouter(prefix="/tv", tags=["tradingview"])


class TVSnapshotResponse(BaseModel):
    """Compact projection of TVIndicatorSnapshot for dashboard consumption."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    stc_value: Optional[float] = None
    stc_state: Optional[str] = None
    composite_score: Optional[float] = None
    regime: Optional[str] = None
    atr_value: Optional[float] = None
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    ib_range: Optional[float] = None
    phase_oscillator: Optional[float] = None
    is_compressed: bool = False
    corey_score: Optional[float] = None
    corey_bias: Optional[str] = None
    vwap: Optional[float] = None
    data_quality: str = "unavailable"  # "live" | "stale" | "unavailable"


class TVHealthResponse(BaseModel):
    available: bool
    cli_found: bool
    cdp_connected: bool


def _unavailable(symbol: str) -> TVSnapshotResponse:
    return TVSnapshotResponse(symbol=symbol, data_quality="unavailable")


@router.get("/snapshot", response_model=TVSnapshotResponse)
async def get_snapshot(
    symbol: str = Query(..., min_length=1, max_length=20, description="Ticker symbol (e.g., MES, MCL, MNQ)"),
):
    """
    Fetch a full TVIndicatorSnapshot for the given symbol.

    Returns data_quality='unavailable' with all fields None if TradingView
    Desktop is offline — never raises, so the dashboard can always render.
    """
    try:
        bridge = get_tv_bridge()
        # TVIndicatorBridge.get_snapshot is synchronous (subprocess-based).
        # Run it in a thread to avoid blocking the event loop.
        snap = await asyncio.to_thread(bridge.get_snapshot, symbol)
        return TVSnapshotResponse(
            symbol=symbol,
            stc_value=snap.stc_value,
            stc_state=snap.stc_state,
            composite_score=snap.composite_score,
            regime=snap.regime,
            atr_value=snap.atr_value,
            ib_high=snap.ib_high,
            ib_low=snap.ib_low,
            ib_range=snap.ib_range,
            phase_oscillator=snap.phase_oscillator,
            is_compressed=bool(snap.is_compressed),
            corey_score=snap.corey_score,
            corey_bias=snap.corey_bias,
            vwap=snap.vwap,
            data_quality=snap.data_quality or "unavailable",
        )
    except Exception as exc:
        logger.warning("[/tv/snapshot] bridge error for %s: %s", symbol, exc)
        return _unavailable(symbol)


@router.get("/health", response_model=TVHealthResponse)
async def tv_health():
    """Report TradingView bridge availability without fetching a snapshot."""
    try:
        bridge = get_tv_bridge()
        available = await asyncio.to_thread(bridge.is_available)
        # cli_found is derivable from the bridge's internal state; recompute
        # here defensively so the dashboard sees a stable contract.
        import shutil as _sh

        cli_found = _sh.which("tv") is not None
        return TVHealthResponse(
            available=bool(available),
            cli_found=cli_found,
            cdp_connected=bool(available),
        )
    except Exception as exc:
        logger.warning("[/tv/health] bridge error: %s", exc)
        return TVHealthResponse(available=False, cli_found=False, cdp_connected=False)
