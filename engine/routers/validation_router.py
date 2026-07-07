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
    """Return live paper-trading readiness with per-gate pass/fail status.

    Emits the frontend ReadinessReport contract
    ``{ready_for_live, all_checks_pass, checks:[{name,passed,value,requirement,
    critical}], passed, total, summary}`` computed from live paper_trades via
    ``ValidationMetrics().compute()`` (the same source /validation/status uses)
    against the canonical TARGETS. Previously returned a static criteria list
    with no live values, so the ReadinessCheckWidget could never show real gates.
    """
    from analytics.validation_metrics import TARGETS, ValidationMetrics

    def _not_ready(reason: str) -> dict:
        return {
            "ready_for_live": False,
            "all_checks_pass": False,
            "checks": [],
            "passed": 0,
            "total": 0,
            "summary": "NOT READY",
            "error": reason,
        }

    try:
        result = ValidationMetrics().compute()
    except Exception as exc:  # fail-soft: never 500 the readiness widget
        logger.warning("readiness-check: ValidationMetrics.compute() failed: %s", exc)
        return _not_ready(str(exc))

    tm = result.get("targets_met", {}) or {}
    m = result.get("metrics", {}) or {}

    checks = [
        {
            "name": "Trading Days",
            "passed": bool(tm.get("days_30")),
            "value": f"{m.get('days_elapsed', 0)} days",
            "requirement": f"≥{TARGETS['min_days']} days",
            "critical": True,
        },
        {
            "name": "Trade Count",
            "passed": bool(tm.get("min_trades_60")),
            "value": str(m.get("total_trades", 0)),
            "requirement": f"≥{TARGETS['min_trades']} trades",
            "critical": True,
        },
        {
            "name": "Win Rate",
            "passed": bool(tm.get("win_rate_55pct")),
            "value": str(m.get("win_rate_pct", "—")),
            "requirement": f"≥{TARGETS['min_win_rate_pct']:.0f}%",
            "critical": True,
        },
        {
            "name": "Profit Factor",
            "passed": bool(tm.get("profit_factor_2_0")),
            "value": str(m.get("profit_factor", "—")),
            "requirement": f"≥{TARGETS['min_profit_factor']}",
            "critical": True,
        },
        {
            "name": "Sharpe Ratio",
            "passed": bool(tm.get("sharpe_1_5")),
            "value": str(m.get("sharpe_ratio", "—")),
            "requirement": f"≥{TARGETS['min_sharpe']}",
            "critical": True,
        },
        {
            "name": "Max Drawdown",
            "passed": bool(tm.get("drawdown_15pct")),
            "value": f"{m.get('max_drawdown_pct', 0)}%",
            "requirement": f"≤{TARGETS['max_drawdown_pct']:.0f}%",
            "critical": True,
        },
    ]

    all_pass = bool(result.get("all_targets_met"))
    passed = sum(1 for c in checks if c["passed"])
    return {
        "ready_for_live": all_pass,
        "all_checks_pass": all_pass,
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "summary": "READY" if all_pass else "NOT READY",
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
