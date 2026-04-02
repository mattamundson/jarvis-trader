"""
Validation router — expose paper trading validation progress via API.
GET /validation/progress — current metrics vs targets
GET /validation/latest — last computed snapshot
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter

logger = logging.getLogger("jarvis_trader.routers.validation")

router = APIRouter(prefix="/validation", tags=["validation"])


def _get_checker():
    from schedulers.validation_checker import ValidationChecker

    db_path = os.environ.get("DB_PATH", "data/jarvis_trader.db")
    return ValidationChecker(db_path)


@router.get("/progress")
async def get_validation_progress():
    """Return current paper trading validation metrics vs targets."""
    try:
        checker = _get_checker()
        snapshot = checker.compute(lookback_days=30)
        return {"status": "ok", "data": snapshot.to_dict()}
    except Exception as exc:
        logger.error(f"Validation progress error: {exc}")
        return {"status": "error", "message": str(exc)}


@router.get("/readiness-check")
async def get_readiness_check():
    """Return paper trading readiness criteria and current pass/fail status."""
    criteria = [
        {"name": "Win Rate", "target": "≥45%", "description": "Winning trades over total trades"},
        {"name": "Max Drawdown", "target": "<10%", "description": "Maximum peak-to-trough equity decline"},
        {"name": "Trade Count", "target": "≥60 trades in 60 days", "description": "Minimum signal frequency"},
        {"name": "Profit Factor", "target": ">2.0", "description": "Gross profit / gross loss ratio"},
        {"name": "MCL WFE", "target": "≥0.40", "description": "Walk-forward efficiency for MCL 1h"},
        {"name": "MNQ WFE", "target": "≥0.40", "description": "Walk-forward efficiency for MNQ 1h"},
    ]
    return {
        "criteria": criteria,
        "description": "All criteria must be met over 30 consecutive trading days before live capital deployment.",
        "phase": "paper_trading",
    }


@router.get("/targets")
async def get_validation_targets():
    """Return the validation targets required to go live."""
    from schedulers.validation_checker import TARGETS

    return {
        "targets": TARGETS,
        "description": "All targets must be met for 30 consecutive days before live capital deployment.",
    }
