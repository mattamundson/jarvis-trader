"""Safety and loss tracking router."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.models import SafetyStatusResponse
from middleware.rate_limit import limiter

router = APIRouter(prefix="/safety", tags=["safety"])
logger = logging.getLogger(__name__)

# Global references (injected from main.py)
_safety_layer = None
_loss_tracker = None


def inject_dependencies(safety_layer, loss_tracker):
    """Inject global dependencies from main.py"""
    global _safety_layer, _loss_tracker
    _safety_layer = safety_layer
    _loss_tracker = loss_tracker


class KillSwitchActivateBody(BaseModel):
    reason: str = Field(default="MANUAL", description="KillSwitchReason name or label")
    message: str = Field(default="", description="Optional detail message")


class KillSwitchJsonBody(BaseModel):
    """Dashboard command-center payload."""

    activate: bool = Field(default=True)


@router.get("/loss-tracker/status")
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


@router.get("/position-sizing/calculate")
async def calculate_position_sizing(
    symbol: str = "MES",
    account_value: float = 10000.0,
    atr: float = 10.0,
    risk_pct: float = 0.01,
) -> dict[str, Any]:
    """Calculate position size based on risk parameters."""
    try:
        from utils.position_sizing import calculate_contracts

        contracts = calculate_contracts(
            symbol=symbol,
            account_value=account_value,
            atr=atr,
            risk_pct=risk_pct,
        )

        return {
            "symbol": symbol,
            "account_value": account_value,
            "atr": atr,
            "risk_pct": risk_pct,
            "contracts": contracts,
        }
    except Exception as e:
        logger.error(f"[POSITION-SIZING] Calculate error: {e}")
        raise HTTPException(500, f"Failed to calculate position size: {e}") from e


@router.get("/status", response_model=SafetyStatusResponse)
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


@router.get("/circuit-breakers")
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


@router.post("/kill-switch/activate")
async def activate_kill_switch(
    reason: Optional[str] = Query(None, description="KillSwitchReason name (query override)"),
    body: Annotated[Optional[KillSwitchActivateBody], Body()] = None,
) -> dict[str, Any]:
    """Activate the global kill switch (requires API key)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    r = reason or (body.reason if body else "MANUAL")
    msg = body.message if body else ""
    _safety_layer.activate_kill_switch(r, msg)
    now = datetime.now(timezone.utc).isoformat()
    st = _safety_layer.get_status()
    ks_reason = st.get("kill_switch_reason")
    reason_str = ks_reason.value if hasattr(ks_reason, "value") else str(ks_reason)
    return {"status": "activated", "reason": reason_str, "activated_at": now}


@router.post("/kill-switch/deactivate")
async def deactivate_kill_switch(
    authorized_by: str = "api",
) -> dict[str, Any]:
    """Deactivate the global kill switch (requires API key)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")

    _safety_layer.deactivate_kill_switch(authorized_by=authorized_by)
    now = datetime.now(timezone.utc).isoformat()
    return {"status": "deactivated", "reason": None, "activated_at": now}


@router.post("/kill-switch")
async def kill_switch_legacy(body: KillSwitchJsonBody) -> dict[str, Any]:
    """Toggle kill switch from dashboard JSON body `{ \"activate\": true|false }`."""
    if body.activate:
        return await activate_kill_switch(
            None,
            KillSwitchActivateBody(reason="MANUAL", message="dashboard"),
        )
    return await deactivate_kill_switch(authorized_by="dashboard")


@router.post("/reset-daily-pnl")
async def reset_daily_pnl() -> dict[str, Any]:
    """Reset SafetyLayer daily PnL counters (testing / manual recovery)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")
    return _safety_layer.reset_daily_pnl()
