"""
Crypto router — expose Freqtrade/crypto module status via API.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger("jarvis_trader.routers.crypto")

router = APIRouter(prefix="/crypto", tags=["crypto"])


def _get_module():
    try:
        from orchestrator import get_orchestrator
        orch = get_orchestrator()
        if orch:
            return orch.get_module("crypto")
    except Exception:
        pass
    return None


@router.get("/status")
async def crypto_status():
    """Return Freqtrade / crypto module health."""
    module = _get_module()
    if not module:
        return {"status": "disabled", "message": "Crypto module not registered. Set CRYPTO_ENABLED=True."}
    health = module.health_check()
    return {
        "status": health.status.value,
        "message": health.message,
        "daily_pnl": health.daily_pnl,
        "open_positions": health.open_positions,
    }


@router.get("/positions")
async def crypto_positions():
    """Return open crypto positions from Freqtrade."""
    module = _get_module()
    if not module:
        return {"positions": []}
    positions = await module.get_positions()
    return {"positions": [
        {
            "symbol": p.symbol,
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "market_value": p.market_value,
            "unrealized_pnl": p.unrealized_pnl,
        }
        for p in positions
    ]}


@router.get("/pnl")
async def crypto_pnl():
    """Return today's crypto P&L."""
    module = _get_module()
    if not module:
        return {"daily_pnl": 0.0, "target": 100.0}
    pnl = await module.get_daily_pnl()
    return {
        "daily_pnl": pnl,
        "target": module.daily_target,
        "progress_pct": round(pnl / module.daily_target * 100, 1) if module.daily_target else 0,
    }


@router.get("/freqtrade/status")
async def freqtrade_status():
    """Get raw Freqtrade status from its REST API."""
    module = _get_module()
    if not module:
        return {"error": "Crypto module not available"}
    try:
        status = await module._bridge.get_status()
        return {"freqtrade": status}
    except Exception as exc:
        return {"error": str(exc)}
