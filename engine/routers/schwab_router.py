"""Schwab connector control endpoints."""

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schwab", tags=["schwab"])

# schwab_connector set by main.py at startup via set_schwab_connector()
schwab_connector = None


def set_schwab_connector(connector) -> None:
    """Wire the SchwabConnector instance in from main.py lifespan."""
    global schwab_connector
    schwab_connector = connector


@router.get("/status")
async def schwab_status():
    if schwab_connector is None:
        return {
            "connected": False,
            "reason": "Schwab connector not initialized (no credentials or SCHWAB_READY=False)",
        }
    return {
        "connected": schwab_connector.is_connected,
        "state": (
            schwab_connector.state.value if hasattr(schwab_connector, "state") else "unknown"
        ),
    }


@router.post("/connect")
async def schwab_connect():
    if schwab_connector is None:
        raise HTTPException(
            503,
            "Schwab connector not initialized — set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in .env",
        )
    try:
        ok = await schwab_connector.initialize()
        if ok:
            return {"status": "connected"}
        return {"status": "failed", "reason": "initialize() returned False — check logs"}
    except Exception as exc:
        raise HTTPException(500, f"Schwab connect failed: {exc}") from exc


@router.post("/disconnect")
async def schwab_disconnect():
    if schwab_connector is None:
        raise HTTPException(503, "Schwab connector not initialized")
    ok = await schwab_connector.disconnect()
    return {"status": "disconnected" if ok else "disconnect_failed"}
