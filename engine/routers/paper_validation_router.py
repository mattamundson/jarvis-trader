"""
Paper Validation Router — expose validation metrics via API.

Endpoints:
  GET /paper/validation/progress — current metrics vs thresholds
  GET /paper/validation/trades — list of all paper trades
  POST /paper/validation/record — record a new trade
  GET /paper/validation/status — overall pass/fail + days remaining
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper/validation", tags=["paper_validation"])


class RecordTradeRequest(BaseModel):
    """Request to record a paper trade."""

    model_config = ConfigDict(from_attributes=True)

    instrument: str = Field(..., description="Symbol (MCL, MNQ, etc)")
    entry_price: float = Field(..., description="Entry price")
    exit_price: float = Field(..., description="Exit price")
    pnl: float = Field(..., description="Profit/loss")
    setup_grade: str = Field("unknown", description="Setup grade (A, B, C, etc)")


class ValidationProgressResponse(BaseModel):
    """Validation progress response."""

    model_config = ConfigDict(from_attributes=True)

    instrument: str
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    days_active: int
    is_validated: bool
    pass_fail: dict
    thresholds: dict


def _get_tracker():
    """Lazy-load tracker singleton."""
    from paper.validation_tracker import ValidationTracker

    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    return ValidationTracker(data_dir=data_dir)


@router.get("/progress")
async def get_validation_progress(instrument: str = "MCL"):
    """Get current validation metrics vs thresholds."""
    try:
        tracker = _get_tracker()
        progress = tracker.get_progress(instrument)
        return {"status": "ok", "data": progress}
    except Exception as exc:
        logger.error(f"Validation progress error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/trades")
async def get_validation_trades(instrument: str = "MCL"):
    """Get all recorded trades for an instrument."""
    try:
        tracker = _get_tracker()
        trades = tracker.get_all_trades(instrument)
        return {"status": "ok", "instrument": instrument, "trades": trades}
    except Exception as exc:
        logger.error(f"Validation trades query error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.post("/record")
async def record_validation_trade(request: RecordTradeRequest):
    """Record a new paper trade."""
    try:
        tracker = _get_tracker()
        tracker.record_trade(
            instrument=request.instrument,
            entry_price=request.entry_price,
            exit_price=request.exit_price,
            pnl=request.pnl,
            setup_grade=request.setup_grade,
        )
        progress = tracker.get_progress(request.instrument)
        return {"status": "ok", "message": "Trade recorded", "data": progress}
    except Exception as exc:
        logger.error(f"Trade recording error: {exc}")
        raise HTTPException(500, str(exc)) from exc


@router.get("/status")
async def get_validation_status():
    """Get overall validation status."""
    try:
        tracker = _get_tracker()
        data = tracker.get_dashboard_data()
        return {"status": "ok", "data": data}
    except Exception as exc:
        logger.error(f"Validation status error: {exc}")
        raise HTTPException(500, str(exc)) from exc
