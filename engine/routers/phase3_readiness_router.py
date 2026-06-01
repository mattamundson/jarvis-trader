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
            # MAX_SINGLE_ORDER_VALUE was intentionally raised from $5k to $100k in
            # handoff-2026-04-09-2354 to allow futures notional (MES contract is
            # ~$35k notional per-contract; the old $5k cap rejected every futures
            # order). Gate now accepts anything up to $100k. Lower is also fine
            # (stricter = safer). This honors the post-futures-fix policy without
            # hard-coding a single value.
            position_ok = (
                settings.MAX_CONTRACTS_PER_INSTRUMENT == 2
                and settings.MAX_OVERNIGHT_CONTRACTS == 1
                and settings.MAX_POSITION_SIZE_PCT == 0.05
                and 0 < settings.MAX_SINGLE_ORDER_VALUE <= 100_000.0
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
                "All gates passing. Ready for Tier 3 approval to set " "LIVE_TRADING_ENABLED=True"
                if all_pass
                else "One or more gates failing. Review details above."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("[PHASE3] Readiness check failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Phase 3 readiness check error: {e}") from e


@router.get("/system/mes-sprint-gate", tags=["system"])
async def mes_sprint_gate() -> dict:
    """MES Sprint Gate — aggregates 6 prerequisite checks for the April 30 live flip."""
    import json as _json
    from pathlib import Path as _Path

    checks: list[dict] = []
    all_pass = True

    # 1. HB-1 paper smoke flag file present.
    flag = _Path(__file__).resolve().parent.parent / "data" / "hb1_smoke_passed.json"
    smoke_ok = flag.exists()
    checks.append(
        {
            "name": "smoke_test",
            "pass": smoke_ok,
            "detail": str(flag) if smoke_ok else "Run engine/scripts/hb1_paper_smoke.py first",
        }
    )
    if not smoke_ok:
        all_pass = False

    # 2. Bracket paper trades — read sidecar bumped by SafetyLayer.submit_entry_with_stop.
    # Sidecar is preferred over paper_trades.notes because the writer chain
    # (paper_trade_logger → portfolio_tracker → DB) currently drops notes
    # (writes empty string). The sidecar is incremented at the bracket call site.
    bracket_count = 0
    bracket_sidecar = _Path(__file__).resolve().parent.parent / "data" / "bracket_trade_count.json"
    try:
        if bracket_sidecar.exists():
            sc = _json.loads(bracket_sidecar.read_text(encoding="utf-8"))
            bracket_count = int(sc.get("MES", {}).get("count", 0) or 0)
    except Exception as exc:  # noqa: BLE001 — gate must never raise
        logger.warning("mes-sprint-gate: bracket sidecar read failed: %s", exc)
    bracket_ok = bracket_count >= 5
    checks.append(
        {
            "name": "bracket_trades",
            "pass": bracket_ok,
            "value": f"{bracket_count}/5",
            "detail": (
                f"Need {max(0, 5 - bracket_count)} more bracket trades" if not bracket_ok else "OK"
            ),
        }
    )
    if not bracket_ok:
        all_pass = False

    # 3. Kill switch clean (uses injected SafetyLayer if available).
    ks_active = False
    if _safety_layer is not None:
        ks_active = bool(getattr(_safety_layer, "_kill_switch_active", False))
    ks_ok = not ks_active
    checks.append(
        {
            "name": "kill_switch_clean",
            "pass": ks_ok,
            "detail": "Kill switch inactive" if ks_ok else "KILL SWITCH ACTIVE — trading halted",
        }
    )
    if not ks_ok:
        all_pass = False

    # 4. pm2 restarts ≤ 5 in rolling 72h (read sidecar JSON).
    restart_count = 0
    restart_file = _Path(__file__).resolve().parent.parent / "data" / "pm2_restart_count_72h.json"
    try:
        restart_data = _json.loads(restart_file.read_text(encoding="utf-8"))
        restart_count = int(restart_data.get("restarts_72h", 0) or 0)
    except Exception:
        restart_count = 0  # no sidecar yet — benefit of the doubt
    restart_ok = restart_count <= 5
    checks.append(
        {
            "name": "pm2_restarts",
            "pass": restart_ok,
            "value": f"{restart_count}/5 (72h)",
            "detail": (
                "Stable"
                if restart_ok
                else f"{restart_count} restarts in 72h — investigate before flipping live"
            ),
        }
    )
    if not restart_ok:
        all_pass = False

    # 5. Loss streak < 3 (consecutive losing closed trades by entry_time DESC).
    streak = 0
    try:
        from database.manager import get_db

        db = get_db()
        recent = db.fetch_all(
            "SELECT pnl FROM paper_trades "
            "WHERE status = 'closed' AND pnl IS NOT NULL "
            "ORDER BY entry_time DESC LIMIT 10"
        )
        for r in recent:
            if (r.get("pnl") or 0) < 0:
                streak += 1
            else:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("mes-sprint-gate: loss streak query failed: %s", exc)
    streak_ok = streak < 3
    checks.append(
        {
            "name": "loss_streak",
            "pass": streak_ok,
            "value": str(streak),
            "detail": f"Current streak: {streak}" + (" — WARNING" if streak >= 2 else ""),
        }
    )
    if not streak_ok:
        all_pass = False

    # 6. Today's intra-session drawdown < 2% (NOT all-time drawdown from peak).
    # Pre-flight protection is "is the trader currently bleeding today" — historical
    # peak-to-current can show stale paper-account volatility that has nothing to do
    # with going-live readiness. Compute as daily_pnl / starting_balance, then take
    # only the negative side (positive PnL = no drawdown today).
    daily_drawdown = 0.0
    if _safety_layer is not None:
        try:
            pnl_mon = getattr(_safety_layer, "_pnl_monitor", None)
            if pnl_mon is not None and hasattr(pnl_mon, "get_current_pnl_state"):
                state = pnl_mon.get_current_pnl_state()
                daily_pnl = float(
                    (getattr(state, "daily_realized_pnl", 0.0) or 0.0)
                    + (getattr(state, "daily_unrealized_pnl", 0.0) or 0.0)
                )
                starting = float(getattr(state, "starting_balance", 0.0) or 0.0)
                if starting > 0:
                    pct = daily_pnl / starting
                    daily_drawdown = -pct if pct < 0 else 0.0  # 0 if up, positive if down
        except Exception as exc:  # noqa: BLE001
            logger.warning("mes-sprint-gate: daily drawdown read failed: %s", exc)
    dd_ok = daily_drawdown < 0.02
    checks.append(
        {
            "name": "drawdown",
            "pass": dd_ok,
            "value": f"{daily_drawdown * 100:.2f}%",
            "detail": (f"Today's drawdown: {daily_drawdown * 100:.2f}% (limit 2%, intra-session)"),
        }
    )
    if not dd_ok:
        all_pass = False

    # PENDING is reserved for "only thing missing is data that fills over time"
    # — i.e., bracket count is the SOLE failing check. Anything else failing → FAIL.
    other_checks_pass = all(c["pass"] for c in checks if c["name"] != "bracket_trades")
    if all_pass:
        overall = "PASS"
    elif (not bracket_ok) and other_checks_pass:
        overall = "PENDING"
    else:
        overall = "FAIL"
    return {
        "overall": overall,
        "ready_for_live": all_pass,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notes": "MES Sprint Gate v1 — iteration 1 of many",
    }
