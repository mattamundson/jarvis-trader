"""
Validation router — expose paper trading validation progress via API.
DEPRECATED: GET /validation/progress redirects to /paper/validation/progress (canonical endpoint).
GET /validation/readiness-check — readiness criteria
GET /validation/targets — validation targets
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from starlette.responses import RedirectResponse

logger = logging.getLogger("jarvis_trader.routers.validation")

router = APIRouter(prefix="/validation", tags=["validation"])


def _get_checker():
    from schedulers.validation_checker import ValidationChecker

    db_path = os.environ.get("DB_PATH", "data/jarvis_trader.db")
    return ValidationChecker(db_path)


@router.get("/progress")
async def get_validation_progress():
    """
    DEPRECATED: This endpoint is deprecated.
    Redirect to the canonical endpoint at /paper/validation/progress.
    """
    return RedirectResponse(url="/paper/validation/progress", status_code=301)


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
