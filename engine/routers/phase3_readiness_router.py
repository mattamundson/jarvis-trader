"""
Phase 3 live-trading readiness gate — single endpoint extracted from main.py.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["system", "phase3"])

_safety_layer = None


def inject_dependencies(safety_layer) -> None:
    global _safety_layer
    _safety_layer = safety_layer


@router.get("/system/phase3-readiness")
async def get_phase3_readiness() -> dict:
    """
    Phase 3 Live Trading Readiness Gate.

    Checks validation progress, safety layer, config flags, IBKR paper settings,
    and human-approval requirements.
    """
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    try:
        gates = {}
        all_pass = True

        try:
            from pathlib import Path

            from paper.validation_tracker import ValidationTracker

            tracker = ValidationTracker(data_dir=Path(os.environ.get("DATA_DIR", "data")))
            validation_ok = True
            validation_details = {}

            for instrument in ["MCL", "MNQ"]:
                progress = tracker.get_progress(instrument)
                pass_fail = progress.get("pass_fail", {})
                is_validated = all(v for v in pass_fail.values())
                validation_details[instrument] = {
                    "is_validated": is_validated,
                    "profit_factor": progress.get("profit_factor", 0),
                    "sharpe_ratio": progress.get("sharpe_ratio", 0),
                    "win_rate_pct": progress.get("win_rate_pct", 0),
                    "total_trades": progress.get("total_trades", 0),
                    "days_active": progress.get("days_active", 0),
                    "max_drawdown_pct": progress.get("max_drawdown_pct", 0),
                }
                if not is_validated:
                    validation_ok = False

            gates["validation_gates"] = {
                "passed": validation_ok,
                "details": validation_details,
            }
            if not validation_ok:
                all_pass = False
        except Exception as e:
            logger.warning("[PHASE3] Validation check failed: %s", e)
            gates["validation_gates"] = {"passed": False, "error": str(e)}
            all_pass = False

        try:
            cb = _safety_layer.check_circuit_breakers()
            safety_ok = not (
                cb.get("daily_limit_breached")
                or cb.get("drawdown_breached")
                or cb.get("kill_switch_active")
            )
            gates["safety_tests"] = {
                "passed": safety_ok,
                "details": {
                    "daily_limit_breached": cb.get("daily_limit_breached", False),
                    "drawdown_breached": cb.get("drawdown_breached", False),
                    "kill_switch_active": cb.get("kill_switch_active", False),
                },
            }
            if not safety_ok:
                all_pass = False
        except Exception as e:
            logger.warning("[PHASE3] Safety check failed: %s", e)
            gates["safety_tests"] = {"passed": False, "error": str(e)}
            all_pass = False

        live_disabled = not settings.LIVE_TRADING_ENABLED
        gates["live_trading_disabled"] = {
            "passed": live_disabled,
            "details": {"live_trading_enabled": settings.LIVE_TRADING_ENABLED},
        }
        if not live_disabled:
            all_pass = False

        try:
            status = _safety_layer.get_status()
            kill_switch_present = status is not None
            gates["kill_switch_functional"] = {
                "passed": kill_switch_present,
                "details": {
                    "can_toggle": True,
                    "endpoints": [
                        "POST /safety/kill-switch/activate",
                        "POST /safety/kill-switch/deactivate",
                    ],
                },
            }
        except Exception as e:
            logger.warning("[PHASE3] Kill switch check failed: %s", e)
            gates["kill_switch_functional"] = {"passed": False, "error": str(e)}
            all_pass = False

        try:
            position_ok = (
                settings.MAX_CONTRACTS_PER_INSTRUMENT == 2
                and settings.MAX_OVERNIGHT_CONTRACTS == 1
                and settings.MAX_POSITION_SIZE_PCT == 0.05
                and settings.MAX_SINGLE_ORDER_VALUE == 5000.0
                and settings.MAX_MARGIN_UTILIZATION == 0.40
            )
            gates["position_limits_verified"] = {
                "passed": position_ok,
                "details": {
                    "max_contracts": settings.MAX_CONTRACTS_PER_INSTRUMENT,
                    "max_overnight": settings.MAX_OVERNIGHT_CONTRACTS,
                    "max_position_pct": settings.MAX_POSITION_SIZE_PCT,
                    "max_order_value": settings.MAX_SINGLE_ORDER_VALUE,
                    "max_margin": settings.MAX_MARGIN_UTILIZATION,
                },
            }
            if not position_ok:
                all_pass = False
        except Exception as e:
            logger.warning("[PHASE3] Position limits check failed: %s", e)
            gates["position_limits_verified"] = {"passed": False, "error": str(e)}
            all_pass = False

        ibkr_paper = settings.IBKR_PAPER_MODE and settings.IBKR_PORT == 4002
        gates["ibkr_paper_validated"] = {
            "passed": ibkr_paper,
            "details": {
                "paper_mode_enabled": settings.IBKR_PAPER_MODE,
                "port": settings.IBKR_PORT,
                "expected_port": 4002,
            },
        }
        if not ibkr_paper:
            all_pass = False

        human_approval_ok = settings.REQUIRE_HUMAN_APPROVAL
        gates["human_approval_required"] = {
            "passed": human_approval_ok,
            "details": {"require_human_approval": settings.REQUIRE_HUMAN_APPROVAL},
        }
        if not human_approval_ok:
            all_pass = False

        return {
            "overall_ready": all_pass,
            "gates": gates,
            "notes": (
                "All gates passing. Ready for Tier 3 approval to set "
                "LIVE_TRADING_ENABLED=True"
                if all_pass
                else "One or more gates failing. Review details above."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("[PHASE3] Readiness check failed: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Phase 3 readiness check error: {e}"
        ) from e
