"""Safety and loss tracking router."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.models import KillSwitchToggleResponse, SafetyStatusResponse
from middleware.rate_limit import limiter
from risk.safety_layer import KillSwitchReason

router = APIRouter(prefix="/safety", tags=["safety"])
logger = logging.getLogger(__name__)

# Global references (injected from main.py)
_safety_layer = None
_loss_tracker = None
_alert_manager = None


def inject_dependencies(safety_layer, loss_tracker):
    """Inject global dependencies from main.py"""
    global _safety_layer, _loss_tracker
    _safety_layer = safety_layer
    _loss_tracker = loss_tracker


def inject_alert_manager(manager) -> None:
    """Inject the AlertManager singleton so /safety/alerts/history can read its log."""
    global _alert_manager
    _alert_manager = manager


class KillSwitchActivateBody(BaseModel):
    reason: str = Field(default="MANUAL", description="KillSwitchReason name or label")
    message: str = Field(default="", description="Optional detail message")


class KillSwitchJsonBody(BaseModel):
    """Dashboard command-center payload."""

    activate: bool = Field(default=True)


@router.get(
    "/loss-tracker/status",
    description="Get loss tracker status including halt state, resume time, last trade symbol, and loss threshold configuration.",
)
async def get_loss_tracker_status() -> dict[str, Any]:
    """Get loss tracker status.

    Returns:
        halted: Whether trading is halted
        halt_until: ISO timestamp when trading resumes (if halted)
        last_trade_symbol: Which symbol was last traded
        last_trade_timestamp: When the last trade executed
        config: Loss threshold configuration
    """
    if _loss_tracker is None:
        raise HTTPException(503, detail="Loss tracker not initialized")
    try:
        return _loss_tracker.get_status()
    except Exception as e:
        logger.error(f"[LOSS-TRACKER] Status query failed: {e}")
        raise HTTPException(500, f"Failed to get loss tracker status: {e}") from e


@router.get(
    "/position-sizing/calculate",
    description="Calculate recommended position size based on symbol, account value, ATR, and risk percentage for position sizing guidance.",
)
async def calculate_position_sizing(
    symbol: str = "MES",
    account_value: float = 10000.0,
    atr: float = 10.0,
    risk_pct: float = 0.01,
) -> dict[str, Any]:
    """Calculate position size based on risk parameters."""
    try:
        from utils.position_sizing import calculate_position_size

        result = calculate_position_size(
            symbol=symbol,
            account_value=account_value,
            atr=atr,
            risk_pct=risk_pct,
        )

        return {
            "symbol": result.symbol,
            "account_value": result.account_value,
            "atr": atr,
            "risk_pct": risk_pct,
            "contracts": result.contracts,
            "risk_per_trade": result.risk_per_trade,
            "stop_distance": result.stop_distance,
            "dollar_risk_per_contract": result.dollar_risk_per_contract,
            "reasoning": result.reasoning,
        }
    except Exception as e:
        logger.error(f"[POSITION-SIZING] Calculate error: {e}")
        raise HTTPException(500, f"Failed to calculate position size: {e}") from e


@router.get(
    "/status",
    response_model=SafetyStatusResponse,
    description="Aggregated safety status and PnL snapshot including kill switch, circuit breakers, daily limits, drawdown, and portfolio equity.",
)
@limiter.limit("10/minute")
async def get_safety_status(request: Request) -> dict[str, Any]:
    """Aggregated safety + PnL snapshot for dashboards and scripts."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    base = _safety_layer.get_status()
    cb = _safety_layer.check_circuit_breakers()
    orders_last = _safety_layer.orders_in_last_minute()

    consecutive_losses = 0
    if _loss_tracker is not None and hasattr(_loss_tracker, "get_consecutive_losses"):
        try:
            consecutive_losses = int(_loss_tracker.get_consecutive_losses())
        except Exception:
            consecutive_losses = 0

    pnl_source = "memory"
    current_balance = float(base.get("current_equity") or 0.0)
    starting_balance = float(base.get("equity_peak") or 0.0)
    pm = getattr(_safety_layer, "_pnl_monitor", None)
    if pm is not None and hasattr(pm, "get_current_pnl_state"):
        try:
            st = pm.get_current_pnl_state()
            pnl_source = getattr(st, "source", pnl_source)
            current_balance = float(
                getattr(st, "current_balance", current_balance) or current_balance
            )
            starting_balance = float(
                getattr(st, "starting_balance", starting_balance) or starting_balance
            )
        except Exception:
            pass

    daily_pnl = float(cb.get("daily_pnl", 0.0))
    equity = current_balance if current_balance > 0 else max(starting_balance, 1.0)
    daily_pnl_pct = (daily_pnl / equity) if equity else 0.0

    return {
        "kill_switch_active": bool(base.get("is_killed")),
        "kill_switch_reason": base.get("kill_switch_reason"),
        "daily_pnl": daily_pnl,
        "daily_limit": float(cb.get("daily_limit", 0.0)),
        "daily_pnl_pct": daily_pnl_pct,
        "daily_limit_pct": float(cb.get("daily_limit_pct", -0.02)),
        "daily_limit_breached": bool(cb.get("daily_limit_breached")),
        "drawdown_pct": float(cb.get("drawdown_pct", 0.0)),
        "drawdown_limit_pct": float(cb.get("drawdown_limit_pct", -0.10)),
        "drawdown_breached": bool(cb.get("drawdown_breached")),
        "portfolio_equity": current_balance,
        "starting_balance": starting_balance,
        "current_balance": current_balance,
        "pnl_source": pnl_source,
        "orders_last_minute": orders_last,
        "consecutive_losses": consecutive_losses,
        "equity_peak": float(base.get("equity_peak") or 0.0),
        "daily_realized_pnl": float(base.get("daily_realized_pnl") or 0.0),
    }


@router.get(
    "/circuit-breakers",
    description="Circuit breaker snapshot showing daily limit status, drawdown breach state, and all_clear flag for dashboard.",
)
async def get_circuit_breakers() -> dict[str, Any]:
    """Circuit breaker snapshot for dashboards (includes all_clear)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    cb = dict(_safety_layer.check_circuit_breakers())
    orders_last = _safety_layer.orders_in_last_minute()
    cb["orders_last_minute"] = orders_last

    pm = getattr(_safety_layer, "_pnl_monitor", None)
    pnl_source = "memory"
    current_balance = float(_safety_layer._current_equity or 0.0)
    starting_balance = float(_safety_layer._equity_peak or 0.0)
    if pm is not None and hasattr(pm, "get_current_pnl_state"):
        try:
            st = pm.get_current_pnl_state()
            pnl_source = getattr(st, "source", pnl_source)
            current_balance = float(
                getattr(st, "current_balance", current_balance) or current_balance
            )
            starting_balance = float(
                getattr(st, "starting_balance", starting_balance) or starting_balance
            )
        except Exception:
            pass

    cb["pnl_source"] = pnl_source
    cb["current_balance"] = current_balance
    cb["starting_balance"] = starting_balance
    cb["all_clear"] = not (
        cb.get("daily_limit_breached")
        or cb.get("drawdown_breached")
        or cb.get("kill_switch_active")
    )
    return cb


@router.post(
    "/kill-switch/activate",
    response_model=KillSwitchToggleResponse,
    description="Activate the global kill switch with optional reason and message (requires API key authorization).",
)
async def activate_kill_switch(
    reason: Optional[str] = Query(None, description="KillSwitchReason name (query override)"),
    body: Annotated[Optional[KillSwitchActivateBody], Body()] = None,
) -> dict[str, Any]:
    """Activate the global kill switch (requires API key)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    reason_label = reason or (body.reason if body else "manual")
    _safety_layer.activate_kill_switch(
        KillSwitchReason.MANUAL, f"Manual activation: {reason_label}"
    )
    try:
        from notifications.whatsapp import get_notifier
        from websocket.events import emit_kill_switch_change

        asyncio.create_task(get_notifier().alert_kill_switch(reason_label))
        asyncio.create_task(emit_kill_switch_change(active=True, reason=reason_label))
    except Exception as exc:
        logger.warning("[SAFETY] Kill-switch side effects (notify/ws): %s", exc)

    try:
        from notifications.openclaw_notifier import notify_kill_switch as _oc_ks

        asyncio.create_task(_oc_ks(market="ALL", reason=reason_label))
    except Exception as exc:
        logger.warning("[SAFETY] OpenClaw kill-switch notify: %s", exc)

    return {"status": "kill_switch_activated", "reason": reason_label}


@router.post(
    "/kill-switch/deactivate",
    response_model=KillSwitchToggleResponse,
    description="Deactivate the global kill switch to resume trading after halt (requires API key authorization).",
)
async def deactivate_kill_switch(
    authorized_by: str = "matt_dashboard",
) -> dict[str, Any]:
    """Deactivate the global kill switch (requires API key)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    _safety_layer.deactivate_kill_switch(authorized_by=authorized_by)
    try:
        from websocket.events import emit_kill_switch_change

        asyncio.create_task(emit_kill_switch_change(active=False, reason="Manual deactivation"))
    except Exception as exc:
        logger.warning("[SAFETY] Kill-switch WS emit on deactivate: %s", exc)

    return {"status": "kill_switch_deactivated", "reason": None}


@router.post(
    "/kill-switch",
    description="Toggle kill switch state via dashboard JSON body with activate boolean flag (legacy endpoint).",
)
async def kill_switch_legacy(body: KillSwitchJsonBody) -> dict[str, Any]:
    """Toggle kill switch from dashboard JSON body `{ \"activate\": true|false }`."""
    if body.activate:
        return await activate_kill_switch(
            None,
            KillSwitchActivateBody(reason="MANUAL", message="dashboard"),
        )
    return await deactivate_kill_switch(authorized_by="dashboard")


@router.get(
    "/alerts/history",
    description="Return the last 50 P&L threshold alerts fired today by the AlertManager.",
)
async def get_alerts_history(limit: int = 50) -> dict[str, Any]:
    """
    Returns the most recent P&L push alerts fired today, newest first.

    Each entry includes:
      - ts:      ISO timestamp (Chicago time)
      - key:     threshold key (e.g. 'daily_loss_75pct', 'drawdown_5pct')
      - message: the full alert message that was sent

    Also includes a 'fired_keys' dict showing which thresholds fired today.
    """
    if _alert_manager is None:
        return {
            "alerts": [],
            "fired_keys": {},
            "total_today": 0,
            "status": "AlertManager not initialized",
        }
    try:
        cap = max(1, min(limit, 200))
        history = _alert_manager.get_history(limit=cap)
        fired = _alert_manager.get_fired_keys()
        return {
            "alerts": history,
            "fired_keys": fired,
            "total_today": len(history),
            "status": "ok",
        }
    except Exception as exc:
        logger.error("[ALERTS] get_alerts_history failed: %s", exc)
        raise HTTPException(500, f"Failed to retrieve alert history: {exc}") from exc


@router.post(
    "/reset-daily-pnl",
    description="Reset SafetyLayer daily PnL counters for testing or manual recovery after circuit breaker triggers.",
)
async def reset_daily_pnl() -> dict[str, Any]:
    """Reset SafetyLayer daily PnL counters (testing / manual recovery)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")
    return _safety_layer.reset_daily_pnl()


@router.get(
    "/position-size",
    description="Calculate recommended position size using ATR-based framework with hardcoded contract limits respecting drawdown state.",
)
async def get_position_size(
    symbol: str = "MES",
    atr: float = 10.0,
    account_value: float = 10000.0,
    current_drawdown: float = 0.0,
) -> dict[str, Any]:
    """
    Calculate recommended position size using SafetyLayer ATR-based framework.

    ADVISORY ONLY — respects hardcoded contract and position size limits.

    Query Parameters:
        symbol: Trading symbol (e.g., "MES", "MCL")
        atr: Average True Range in points
        account_value: Current account equity in dollars
        current_drawdown: Current drawdown from peak as percentage (default 0.0)

    Returns:
        Recommended contracts, risk amount, sizing details, and hardcoded limits
    """
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    try:
        return _safety_layer.get_recommended_size(
            symbol=symbol,
            atr=atr,
            account_value=account_value,
            current_drawdown=current_drawdown,
        )
    except Exception as e:
        logger.error(f"[POSITION-SIZE] Calculate error: {e}")
        raise HTTPException(500, f"Failed to calculate position size: {e}") from e
