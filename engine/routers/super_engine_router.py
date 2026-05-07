"""
Super-Engine Router — status and health of advanced JARVIS components.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("jarvis_trader.routers.super_engine")

router = APIRouter(prefix="/super-engine", tags=["super-engine"])

# Global references (assigned in main.py lifespan)
registry = {
    "polymarket": None,
    "openbb": None,
    "sentiment_bridge": None,
    "model_drawer": None,
    "arb_scout": None,
    "regime_guard": None
}

def inject_super_engine(components: dict):
    """Update global component registry."""
    global registry
    registry.update(components)

@router.get("/status")
async def get_engine_status():
    """Return status of all Super-Engine components."""
    status = {}
    for key, instance in registry.items():
        if instance:
            status[key] = {
                "active": True,
                "type": type(instance).__name__,
                "last_check": datetime.now().isoformat()
            }
            # Component-specific health details
            if key == "model_drawer" and hasattr(instance, "current_model"):
                status[key]["model_loaded"] = instance.current_model is not None
            if key == "arb_scout" and hasattr(instance, "paired_assets"):
                status[key]["pairs_count"] = len(instance.paired_assets)
            if key == "regime_guard" and hasattr(instance, "last_regime"):
                status[key]["current_regime"] = instance.last_regime
                status[key]["last_check"] = instance.last_check.isoformat() if instance.last_check else None
        else:
            status[key] = {"active": False}

    return status

@router.get("/polymarket/balance")
async def get_poly_balance():
    """Fetch balance from Polymarket connector."""
    poly = registry.get("polymarket")
    if not poly:
        raise HTTPException(status_code=503, detail="Polymarket connector not active")

    try:
        # In a real implementation, we'd call the exchange API
        return {"balance": 1000.0, "currency": "USDC", "chain": "Polygon"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

