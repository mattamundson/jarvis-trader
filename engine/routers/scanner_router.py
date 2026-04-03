"""
Signal Scanner API Routes
===========================
Endpoints for controlling the scheduled signal scanner.

Routes:
  GET  /scanner/status       — Current scanner state
  POST /scanner/trigger      — Manual scan (one-time)
  POST /scanner/pause        — Pause automatic scanning
  POST /scanner/resume       — Resume automatic scanning
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.scanner")

router = APIRouter(prefix="/scanner", tags=["scanner"])

# Global reference to scanner (injected from main.py)
_signal_scanner = None


def inject_dependencies(scanner) -> None:
    """Inject SignalScanner instance from main.py."""
    global _signal_scanner
    _signal_scanner = scanner


class ScannerStatusResponse(BaseModel):
    """Current scanner state."""

    active: bool
    symbols: list[str]
    scan_interval_minutes: int
    last_scan_at: str | None
    next_scan_at: str | None
    total_scans: int
    approvals_created: int
    errors: int


class ScannerActionResponse(BaseModel):
    """Response from scanner action (trigger/pause/resume)."""

    action: str
    status: str
    message: str


@router.get("/status", response_model=ScannerStatusResponse)
async def get_scanner_status() -> dict[str, Any]:
    """
    Get current signal scanner state.

    Returns:
        - active: Whether scanner is actively scanning
        - symbols: Symbols being scanned
        - scan_interval_minutes: How often to scan
        - last_scan_at: ISO timestamp of last scan
        - next_scan_at: ISO timestamp of next scheduled scan
        - total_scans: Total scans run
        - approvals_created: Pending approvals created by scanner
        - errors: Total errors during scanning
    """
    if _signal_scanner is None:
        raise HTTPException(503, detail="Scanner not initialized")

    return _signal_scanner.status()


@router.post("/trigger", response_model=ScannerActionResponse)
async def trigger_manual_scan() -> dict[str, Any]:
    """
    Manually trigger a scan immediately (does not affect schedule).

    Use this to scan on-demand without waiting for the next scheduled scan.
    Does not run if market is closed or scanner is paused.

    Returns:
        - action: "trigger"
        - status: "success" or "skipped"
        - message: Details about why scan ran or was skipped
    """
    if _signal_scanner is None:
        raise HTTPException(503, detail="Scanner not initialized")

    try:
        if not _signal_scanner._active:
            return {
                "action": "trigger",
                "status": "skipped",
                "message": "Scanner is paused",
            }

        import asyncio

        asyncio.create_task(_signal_scanner._run_scan())
        return {
            "action": "trigger",
            "status": "success",
            "message": "Scan started in background",
        }

    except Exception as e:
        logger.error(f"[Scanner] Manual trigger failed: {e}")
        raise HTTPException(500, detail=f"Trigger failed: {e}") from e


@router.post("/pause", response_model=ScannerActionResponse)
async def pause_scanner() -> dict[str, Any]:
    """
    Pause automatic scanning.

    Keeps the background task running but skips the scan logic on each cycle.
    The scanner can be resumed with /scanner/resume.

    Returns:
        - action: "pause"
        - status: "success"
        - message: Confirmation message
    """
    if _signal_scanner is None:
        raise HTTPException(503, detail="Scanner not initialized")

    try:
        await _signal_scanner.pause()
        return {
            "action": "pause",
            "status": "success",
            "message": "Scanner paused — no new scans will run",
        }
    except Exception as e:
        logger.error(f"[Scanner] Pause failed: {e}")
        raise HTTPException(500, detail=f"Pause failed: {e}") from e


@router.post("/resume", response_model=ScannerActionResponse)
async def resume_scanner() -> dict[str, Any]:
    """
    Resume automatic scanning.

    Resumes the scanner after a pause. Has no effect if already running.

    Returns:
        - action: "resume"
        - status: "success"
        - message: Confirmation message
    """
    if _signal_scanner is None:
        raise HTTPException(503, detail="Scanner not initialized")

    try:
        await _signal_scanner.resume()
        return {
            "action": "resume",
            "status": "success",
            "message": "Scanner resumed — will run next cycle",
        }
    except Exception as e:
        logger.error(f"[Scanner] Resume failed: {e}")
        raise HTTPException(500, detail=f"Resume failed: {e}") from e
