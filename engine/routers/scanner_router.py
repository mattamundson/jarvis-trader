"""
Signal Scanner API Routes
===========================
Endpoints for controlling the scheduled signal scanner and viewing intraday signals.

Routes:
  GET  /scanner/status           — Current scanner state
  POST /scanner/trigger          — Manual scan (one-time)
  POST /scanner/pause            — Pause automatic scanning
  POST /scanner/resume           — Resume automatic scanning
  GET  /scanner/signals/latest   — Last 10 intraday signals (any timeframe)
"""

import logging
from collections import deque
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("jarvis_trader.routers.scanner")

router = APIRouter(prefix="/scanner", tags=["scanner"])

# Global reference to scanner (injected from main.py)
_signal_scanner = None

# In-memory deque for intraday signals (max 100 entries)
_signals_deque: deque = deque(maxlen=100)


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


class IntraDaySignal(BaseModel):
    """A single intraday signal entry."""

    symbol: str
    timeframe: str
    timestamp: str  # ISO format
    entry_signal: str
    bias: Optional[str] = None
    regime: Optional[str] = None
    composite_score: Optional[float] = None
    position_size_multiplier: float = 1.0  # Default 1.0 for 1h, 0.5 for 15m

    model_config = ConfigDict(from_attributes=True)


class LatestSignalsResponse(BaseModel):
    """Response containing latest intraday signals."""

    count: int
    signals: list[IntraDaySignal]

    model_config = ConfigDict(from_attributes=True)


def record_signal(
    symbol: str,
    timeframe: str,
    entry_signal: str,
    bias: Optional[str] = None,
    regime: Optional[str] = None,
    composite_score: Optional[float] = None,
    position_size_multiplier: float = 1.0,
) -> None:
    """
    Record an intraday signal in the deque.

    Parameters
    ----------
    symbol : str
        Trading symbol (e.g., "MCL", "MNQ")
    timeframe : str
        Timeframe (e.g., "15m", "1h")
    entry_signal : str
        Signal type (e.g., "ENTRY_NOW", "HOLD", "EXIT_NOW")
    bias : str, optional
        Signal bias (e.g., "STRONG", "LEAN")
    regime : str, optional
        Market regime (e.g., "TRENDING_BULL", "RANGING")
    composite_score : float, optional
        Composite signal score if applicable
    position_size_multiplier : float, optional
        Position size multiplier (1.0 for 1h, 0.5 for 15m)
    """
    signal = IntraDaySignal(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime.utcnow().isoformat() + "Z",
        entry_signal=entry_signal,
        bias=bias,
        regime=regime,
        composite_score=composite_score,
        position_size_multiplier=position_size_multiplier,
    )
    _signals_deque.append(signal)
    # Publish signal event if not HOLD
    try:
        from events.bus import detect_regime_change
        from events.bus import publish as publish_event
        if entry_signal != "HOLD":
            publish_event(
                'signal_fired',
                f'{symbol} {timeframe} {entry_signal}',
                symbol=symbol,
                severity='info'
            )

        # Check for regime change
        if regime:
            old_regime = detect_regime_change(symbol, regime)
            if old_regime and old_regime != regime:
                publish_event(
                    'regime_change',
                    f'{symbol}: {old_regime} → {regime}',
                    symbol=symbol,
                    severity='warn'
                )
                # Notify regime change (asyncio task)
                import asyncio
                try:
                    from notifications.openclaw_notifier import notify_regime_change
                    asyncio.create_task(notify_regime_change(symbol, old_regime, regime))
                except Exception:
                    pass
    except Exception:
        pass

    logger.debug(f"[Scanner] Recorded {symbol} {timeframe} signal: {entry_signal}")


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


@router.get("/signals/latest", response_model=LatestSignalsResponse)
async def get_latest_signals() -> LatestSignalsResponse:
    """
    Get the last 10 intraday signals (any timeframe).

    Returns:
        count: Number of signals returned (0-10)
        signals: List of signal entries with symbol, timeframe, timestamp,
                 entry_signal, bias, regime, composite_score
    """
    try:
        # Convert deque to list and reverse to get most recent first
        signal_list = list(_signals_deque)
        signal_list.reverse()
        latest_10 = signal_list[:10]

        return LatestSignalsResponse(
            count=len(latest_10),
            signals=latest_10,
        )

    except Exception as e:
        logger.error(f"[Scanner] Failed to get latest signals: {e}")
        raise HTTPException(500, detail=f"Failed to get latest signals: {e}") from e
