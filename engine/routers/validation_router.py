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
        {
            "name": "Max Drawdown",
            "target": "<10%",
            "description": "Maximum peak-to-trough equity decline",
        },
        {
            "name": "Trade Count",
            "target": "≥60 trades in 60 days",
            "description": "Minimum signal frequency",
        },
        {
            "name": "Profit Factor",
            "target": ">2.0",
            "description": "Gross profit / gross loss ratio",
        },
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

    return {"targets": TARGETS}


@router.get("/status")
async def get_validation_status():
    """
    30-day paper trading validation dashboard.

    Returns metrics computed directly from SQLite paper_trades:
      - days_elapsed / days_remaining toward 30-day window
      - total_trades, win_rate, profit_factor, Sharpe ratio, max_drawdown_pct
      - targets_met: dict of gate name -> bool
      - status: 'validated' | 'in_progress' | 'no_trades'

    No auth required (read-only).
    """
    from analytics.validation_metrics import ValidationMetrics

    metrics = ValidationMetrics()
    return metrics.compute()


# ── Validation Alert Manager ──────────────────────────────────────────────────

_validation_alert_manager = None


def set_validation_alert_manager(manager) -> None:
    """Inject ValidationAlertManager instance (called from main.py lifespan)."""
    global _validation_alert_manager
    _validation_alert_manager = manager


@router.get("/alerts")
async def get_validation_alerts():
    """
    Return recent validation gate alerts (status transitions from PASS/FAIL).

    Returns:
        {
            "alerts": [list of recent alerts],
            "current_gates": {gate_name: "PASS"|"FAIL"|"UNKNOWN", ...},
            "status": "ok" | "no_manager"
        }
    """
    if _validation_alert_manager is None:
        return {
            "alerts": [],
            "current_gates": {},
            "status": "no_manager",
            "message": "ValidationAlertManager not initialized",
        }

    try:
        alerts = _validation_alert_manager.get_alert_history()
        gates = _validation_alert_manager.get_current_gate_status()
        return {"alerts": alerts, "current_gates": gates, "status": "ok"}
    except Exception as e:
        logger.error(f"Failed to fetch validation alerts: {e}")
        return {"alerts": [], "current_gates": {}, "status": "error", "error": str(e)}
