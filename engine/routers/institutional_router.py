"""
JARVIS TRADER — Institutional Router
====================================
Exposes Volume Profile and Harmonic patterns for the dashboard.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from analysis.breakout_engine import VolumeProfileEngine
from analysis.harmonics_engine import HarmonicEngine
from analysis.regime_engine import RegimeEngine
from data.market_data import MarketDataManager

logger = logging.getLogger("jarvis_trader.routers.institutional")
router = APIRouter(prefix="/institutional", tags=["Institutional"])

_data_manager: MarketDataManager | None = None

def inject_data_manager(dm: MarketDataManager):
    global _data_manager
    _data_manager = dm

@router.get("/profile/{symbol}")
async def get_institutional_profile(symbol: str, timeframe: str = "15m"):
    """
    Get POC, VAH, VAL and Harmonic patterns for a symbol.
    """
    if _data_manager is None:
        raise HTTPException(status_code=503, detail="Market data manager not injected")

    symbol = symbol.upper()
    is_futures = not symbol.startswith(("SPY", "QQQ", "IWM"))

    # Fetch data
    df = await _data_manager.get_bars(
        symbol, lookback_days=10, timeframe=timeframe, is_futures=is_futures
    )

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    # Volume Profile
    vp_engine = VolumeProfileEngine()
    profile = vp_engine.calculate_profile(df)

    # Harmonics
    h_engine = HarmonicEngine()
    patterns = h_engine.detect_patterns(df)

    # Regime
    r_engine = RegimeEngine()
    regime = r_engine.classify(df)

    # Format patterns for JSON
    pattern_data = []
    for p in patterns:
        pattern_data.append({
            "name": p.name,
            "type": p.type,
            "confidence": p.confidence,
            "points": p.points[-1][1], # D point price
            "ratios": p.ratios
        })

    current_price = df["close"].iloc[-1]

    return {
        "symbol": symbol,
        "current_price": current_price,
        "volume_profile": profile,
        "harmonics": pattern_data,
        "regime": {
            "value": regime.regime.value,
            "description": regime.description,
            "adx": regime.adx,
            "atr_ratio": regime.atr_ratio
        },
        "timeframe": timeframe
    }
