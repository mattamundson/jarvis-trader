"""Safety and loss tracking router."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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
@limiter.limit("120/minute")  # read-only status; >=5 dashboard widgets poll it
# through one proxy IP (shared bucket), so the 10/min trading tier 429'd
# normal page loads. Mutating safety endpoints keep their strict limits.
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

    # A9: surface the last kill-switch activation so a consumer can tell a
    # just-recovered-from-halt system from one running clean for hours.
    last_ks_ts = base.get("last_kill_switch_ts")
    time_since_ks: Optional[float] = None
    if last_ks_ts:
        try:
            _ts = datetime.fromisoformat(str(last_ks_ts))
            if _ts.tzinfo is None:
                _ts = _ts.replace(tzinfo=timezone.utc)
            time_since_ks = (datetime.now(timezone.utc) - _ts).total_seconds()
        except (ValueError, TypeError):
            time_since_ks = None

    status = {
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
        "orders_per_minute_limit": cb.get("orders_per_minute_limit"),
        "last_kill_switch_ts": last_ks_ts,
        "last_kill_switch_reason_value": base.get("last_kill_switch_reason_value"),
        "time_since_kill_switch_sec": time_since_ks,
    }
    # Feed the Prometheus safety gauges off this read-path (P1.0b). Tolerant and
    # non-raising — observability must never break the safety endpoint.
    try:
        from monitoring.metrics import sync_safety_gauges

        sync_safety_gauges(status)
    except Exception:  # noqa: BLE001 - metrics are best-effort
        pass
    return status


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

    try:
        from notifications.openclaw_notifier import notify_kill_switch_cleared as _oc_cleared

        asyncio.create_task(_oc_cleared(authorized_by=authorized_by))
    except Exception as exc:
        logger.warning("[SAFETY] Kill-switch cleared notify failed: %s", exc)

    return {"status": "kill_switch_deactivated", "reason": None}


@router.post(
    "/flatten-all",
    description=(
        "Emergency-close every open position via market orders. Kill switch blocks new "
        "discretionary orders but leaves existing positions naked; this is the operator "
        "path to liquidate them. Returns {flattened, order_ids, errors}."
    ),
)
async def flatten_all_positions() -> dict[str, Any]:
    """Close every open position via MKT orders (emergency recovery)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")
    result = await _safety_layer.flatten_all_positions()
    logger.warning(
        "[SAFETY] /safety/flatten-all invoked — flattened=%s order_ids=%s errors=%s",
        result.get("flattened"),
        result.get("order_ids"),
        result.get("errors"),
    )
    return result


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


@router.post(
    "/smoke/bracket",
    description=(
        "HB-1 paper smoke test — fires 1-contract MES bracket directly through the "
        "engine's live IBGatewayManager connection, verifies IB-side parentId linkage, "
        "then cancels all 3 orders. Requires IB paper gateway connected (port 4002). "
        "SAFETY: Refuses to run if IBKR_MARKET_DATA_PORT is set to a live port (4001/7496)."
    ),
)
async def smoke_bracket(
    symbol: str = "MES",
    reference_price: float = 5700.0,
    stop_offset: float = 8.0,
    target_offset: float = 10.0,
) -> dict:
    """Fire a 1-contract bracket smoke test via the engine's live IBKRDataConnector._ib."""
    import main as _main
    from execution.ib_gateway import LIVE_TRADING_PORTS

    ibkr_data = getattr(getattr(_main, "data_manager", None), "ibkr", None)
    if ibkr_data is None or not ibkr_data.is_connected:
        raise HTTPException(
            503,
            detail="IBKRDataConnector not connected — is IB Gateway running?",
        )
    
    # SAFETY: Refuse to run if the data connection is on a live port
    if ibkr_data._port in LIVE_TRADING_PORTS:
        raise HTTPException(
            400,
            detail=(
                f"SAFETY BLOCK: Smoke test cannot run when IBKR_MARKET_DATA_PORT={ibkr_data._port} "
                f"(live port). This test places real orders through the data connector's IB object. "
                f"Unset IBKR_MARKET_DATA_PORT or set it to paper port 4002 to run smoke tests."
            ),
        )

    _ib = getattr(ibkr_data, "_ib", None)
    if _ib is None:
        raise HTTPException(503, detail="IBKRDataConnector._ib is None — not initialised")

    try:
        from ib_async import LimitOrder, StopOrder
    except ImportError as exc:
        raise HTTPException(500, detail="ib_async not installed") from exc

    stop_price = reference_price - stop_offset
    target_price = reference_price + target_offset

    # Resolve and qualify the MES front-month contract using the data connector's method
    try:
        contract = await ibkr_data._resolve_front_month(symbol, "CME")
        qualified = await _ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]
    except Exception as exc:
        raise HTTPException(
            500, detail=f"Contract qualification failed for {symbol}: {exc}"
        ) from exc

    # Use a far-OTM limit order (50% below market) as the entry instead of a MarketOrder.
    # This ensures the smoke test never fills during market hours — cancelling an unfilled
    # limit order leaves zero position risk, whereas cancelling a filled MKT order does not
    # offset the position.
    far_otm_price = round(reference_price * 0.50, 2)
    entry_order = LimitOrder(action="BUY", totalQuantity=1, lmtPrice=far_otm_price)
    entry_trade = _ib.placeOrder(contract, entry_order)
    entry_id: int = entry_trade.order.orderId

    # Place STP child linked to entry
    stp_order = StopOrder(action="SELL", totalQuantity=1, stopPrice=stop_price)
    stp_order.parentId = entry_id
    stp_trade = _ib.placeOrder(contract, stp_order)
    stp_id: int = stp_trade.order.orderId

    # Place TP LMT child linked to entry
    tp_order = LimitOrder(action="SELL", totalQuantity=1, lmtPrice=target_price)
    tp_order.parentId = entry_id
    tp_trade = _ib.placeOrder(contract, tp_order)
    tp_id: int = tp_trade.order.orderId

    logger.info("[SMOKE] orders placed — entry=%s stp=%s tp=%s", entry_id, stp_id, tp_id)

    # Wait briefly for IB to register the orders
    await asyncio.sleep(1.5)

    # Verify parentId linkage from IB's own openTrades()
    open_trades = _ib.openTrades()
    stp_linked = any(
        t.order.orderId == stp_id and t.order.parentId == entry_id for t in open_trades
    )
    tp_linked = any(t.order.orderId == tp_id and t.order.parentId == entry_id for t in open_trades)

    # Cancel all orders to leave zero open risk
    cancelled = []
    for trade, label in ((entry_trade, "entry"), (stp_trade, "STP"), (tp_trade, "TP")):
        try:
            _ib.cancelOrder(trade.order)
            cancelled.append(label)
        except Exception as exc:
            logger.warning("[SMOKE] cancel %s: %s", label, exc)

    pass_flags = {
        "entry_routed_to_ib": entry_id is not None,
        "stp_linked (IB parentId)": stp_linked,
        "tp_linked (IB parentId)": tp_linked,
    }
    all_pass = all(pass_flags.values())
    logger.info("[SMOKE] HB-1 bracket result: %s cancelled=%s", pass_flags, cancelled)

    open_orders_snapshot = [
        {
            "order_id": t.order.orderId,
            "parent_id": t.order.parentId,
            "action": t.order.action,
            "type": t.order.orderType,
            "qty": t.order.totalQuantity,
            "status": t.orderStatus.status,
        }
        for t in open_trades[:10]
    ]
    return {
        "result": "PASS" if all_pass else "FAIL",
        "checks": pass_flags,
        "entry_order_id": entry_id,
        "stp_order_id": stp_id,
        "tp_order_id": tp_id,
        "cancelled_orders": cancelled,
        "open_orders_snapshot": open_orders_snapshot,
    }


@router.get(
    "/account/{account_id}/kill-state",
    description=(
        "Return per-account kill switch state for parallel-paper testing. "
        "When ENABLE_PARALLEL_PAPER=0, mirrors the global kill switch state. "
        "account_id must be 'A' or 'B'."
    ),
)
async def get_account_kill_state(account_id: str) -> dict[str, Any]:
    """Per-account kill switch state (parallel-paper infrastructure)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")
    if account_id not in ("A", "B"):
        raise HTTPException(status_code=400, detail="account_id must be 'A' or 'B'")
    try:
        return _safety_layer.get_per_account_kill_state(account_id)
    except Exception as exc:
        logger.error("[SAFETY] get_account_kill_state(%s) failed: %s", account_id, exc)
        raise HTTPException(500, f"Failed to get account kill state: {exc}") from exc


@router.post(
    "/account/{account_id}/kill-state/clear",
    description=(
        "Admin clear of a per-account kill switch halt. "
        "Requires X-API-Key auth. Logged. "
        "Does NOT affect the global kill switch. "
        "account_id must be 'A' or 'B'."
    ),
)
async def clear_account_kill_state(
    account_id: str,
    request: Request,
    notes: str = "",
) -> dict[str, Any]:
    """Admin manual clear of a per-account halt (human-only path)."""
    if _safety_layer is None:
        raise HTTPException(status_code=503, detail="Safety layer not initialized")
    if account_id not in ("A", "B"):
        raise HTTPException(status_code=400, detail="account_id must be 'A' or 'B'")

    # X-API-Key is enforced by the engine's global auth middleware.
    # Log the caller for audit purposes.
    caller_ip = request.client.host if request.client else "unknown"
    logger.warning(
        "[SAFETY] per-account kill cleared: account=%s notes=%r caller_ip=%s",
        account_id,
        notes,
        caller_ip,
    )
    try:
        _safety_layer.clear_per_account_kill(account_id=account_id, notes=notes)
        return {
            "status": "cleared",
            "account_id": account_id,
            "notes": notes,
        }
    except Exception as exc:
        logger.error("[SAFETY] clear_account_kill_state(%s) failed: %s", account_id, exc)
        raise HTTPException(500, f"Failed to clear account kill state: {exc}") from exc


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


@router.get("/config")
async def get_safety_config():
    """Return current risk parameter configuration (read-only).
    Sourced from settings singleton — reflects .env values at startup.
    """
    from config import settings

    return {
        "max_daily_loss_pct": settings.MAX_DAILY_LOSS_PCT,
        "max_drawdown_pct": settings.MAX_DRAWDOWN_PCT,
        "max_position_size_pct": settings.MAX_POSITION_SIZE_PCT,
        "max_contracts_per_instrument": settings.MAX_CONTRACTS_PER_INSTRUMENT,
        "max_overnight_contracts": settings.MAX_OVERNIGHT_CONTRACTS,
        "max_orders_per_minute": settings.MAX_ORDERS_PER_MINUTE,
        "max_single_order_value": settings.MAX_SINGLE_ORDER_VALUE,
        "max_margin_utilization": settings.MAX_MARGIN_UTILIZATION,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "require_human_approval": settings.REQUIRE_HUMAN_APPROVAL,
        "ibkr_host": settings.IBKR_HOST,
        "ibkr_port": settings.IBKR_PORT,
        "ibkr_client_id": settings.IBKR_CLIENT_ID,
        "ibkr_paper_mode": settings.IBKR_PAPER_MODE,
    }


@router.get("/loss-tracker")
async def get_loss_tracker_summary():
    """Return consecutive loss tracking state."""
    if _loss_tracker is None:
        raise HTTPException(500, "Loss tracker not initialized")
    try:
        return _loss_tracker.get_status()
    except Exception as e:
        logger.error(f"[LOSS-TRACKER] Status query failed: {e}")
        raise HTTPException(500, f"Failed to get loss tracker status: {e}") from e


@router.get("/regime-alert")
async def get_regime_alert():
    """P3-15 regime detector: MES daily RSI and VIX sustained-threshold alerts.

    Checks two conditions:
      C1 PERSISTENT_OVERSOLD: MES daily RSI(14) < 30 for >= 5 consecutive days.
      C2 HIGH_VIX: VIX > 25 for >= 3 consecutive trading days.

    Returns RegimeAlertReport as JSON. `any_alert=true` means at least one
    condition is active — escalate (reduce size, widen stops, or pause signals).
    """
    try:
        from analytics.regime_detector import check_regime_alerts

        report = check_regime_alerts()
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/retirement-status")
async def get_retirement_status(symbol: str = "MES"):
    """P3-39 strategy retirement criteria: rolling win rate, PF, loss streak, drawdown.

    Evaluates 8 checks (R1-R4 RETIRE, P1-P4 PAUSE) against paper trade history.
    Returns RetirementStatus with recommendation: RETIRE | PAUSE | HOLD.
    """
    try:
        from backtest.strategy_retirement import check_retirement_from_db

        status = check_retirement_from_db(symbol.upper())
        return status.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
