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


@router.get("/targets")
async def get_validation_targets():
    """Return the validation targets required to go live."""
    from schedulers.validation_checker import TARGETS

    return {
        "targets": TARGETS,
        "description": "All targets must be met for 30 consecutive days before live capital deployment.",
    }
