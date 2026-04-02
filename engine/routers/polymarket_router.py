"""
Polymarket router — prediction market trading endpoints.
All endpoints paper-only by default (POLYMARKET_ENABLED=False).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger("jarvis_trader.routers.polymarket")

router = APIRouter(prefix="/polymarket", tags=["polymarket"])


def _get_module():
    try:
        from orchestrator import get_orchestrator
        orch = get_orchestrator()
        if orch:
            return orch.get_module("polymarket")
    except Exception:
        pass
    return None


@router.get("/status")
async def polymarket_status():
    """Return Polymarket module health and connection status."""
    module = _get_module()
    if not module:
        return {"status": "disabled", "message": "Polymarket module not registered. Set POLYMARKET_ENABLED=True to enable."}
    health = module.health_check()
    return {
        "status": health.status.value,
        "message": health.message,
        "daily_pnl": health.daily_pnl,
        "open_positions": health.open_positions,
        "regulatory_note": "Polymarket has U.S. regulatory restrictions. Consider Kalshi as CFTC-regulated alternative.",
    }


@router.get("/markets")
async def list_markets():
    """List available Polymarket prediction markets."""
    module = _get_module()
    if not module:
        return {"error": "Polymarket not enabled", "markets": []}
    try:
        markets = module._client.get_markets(active_only=True)
        return {"markets": markets[:50], "count": len(markets)}  # Limit to 50
    except Exception as exc:
        return {"error": str(exc), "markets": []}


@router.get("/scan")
async def scan_markets():
    """Scan for Polymarket trading opportunities."""
    module = _get_module()
    if not module:
        return {"error": "Polymarket not enabled", "opportunities": []}
    try:
        from markets.polymarket.scanner import PolymarketScanner
        scanner = PolymarketScanner(client=module._client)
        opps = scanner.scan()
        return {
            "opportunities": [
                {
                    "token_id": o.token_id,
                    "question": o.question[:80],
                    "yes_price": o.yes_price,
                    "no_price": o.no_price,
                    "spread": o.spread,
                    "volume_24h": o.volume_24h,
                    "type": o.opportunity_type,
                    "confidence": o.confidence,
                }
                for o in opps
            ],
            "count": len(opps),
        }
    except Exception as exc:
        logger.error(f"Polymarket scan error: {exc}")
        return {"error": str(exc), "opportunities": []}


@router.get("/pnl")
async def polymarket_pnl():
    """Return today's Polymarket P&L."""
    module = _get_module()
    if not module:
        return {"daily_pnl": 0.0, "target": 125.0, "status": "disabled"}
    pnl = await module.get_daily_pnl()
    return {
        "daily_pnl": pnl,
        "target": module.daily_target,
        "progress_pct": round(pnl / module.daily_target * 100, 1) if module.daily_target else 0,
    }
