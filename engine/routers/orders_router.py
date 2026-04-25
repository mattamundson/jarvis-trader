"""
JARVIS TRADER — Manual Order Router
=====================================
Bridges the Dashboard's /orders/place endpoint to the OrderRouter execution engine.

Routing:
    POST /orders/place   — Submit a manual order from the Dashboard UI
    GET  /orders/status  — Return the OrderRouter broker connectivity status

The global `OrderRouter` instance is injected at startup via `inject_dependencies()`.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("jarvis_trader.orders_router")

router = APIRouter(tags=["orders"])

# Module-level reference to the shared OrderRouter — injected at startup.
_order_router = None


def inject_dependencies(order_router) -> None:
    """
    Inject the global OrderRouter instance.
    Called from main.py during the lifespan startup block.
    """
    global _order_router
    _order_router = order_router
    logger.info("OrdersRouter: OrderRouter dependency injected")


# ── Request / Response Models ─────────────────────────────────────────────────


class ManualOrderRequest(BaseModel):
    """Payload sent by the Dashboard OrderEntryPanel."""

    symbol: str = Field(..., min_length=1, max_length=20, description="Ticker symbol (e.g. MES)")
    direction: Literal["BUY", "SELL"] = Field(..., description="Order direction")
    quantity: int = Field(..., ge=1, le=100, description="Number of contracts / shares")
    order_type: Literal["MARKET", "LIMIT"] = Field("MARKET", description="Order type")
    limit_price: Optional[float] = Field(None, description="Required when order_type=LIMIT")
    stop_loss: Optional[float] = Field(None, description="Stop-loss price level")
    take_profit: Optional[float] = Field(None, description="Take-profit price level")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("limit_price")
    @classmethod
    def limit_price_required_for_limit_order(cls, v, info):
        if info.data.get("order_type") == "LIMIT" and v is None:
            raise ValueError("limit_price is required when order_type is LIMIT")
        return v


class ManualOrderResponse(BaseModel):
    """Confirmation returned to the Dashboard after order submission."""

    status: str
    fill_id: Optional[str] = None
    symbol: str
    action: str
    quantity: int
    order_type: str
    broker: Optional[str] = None
    message: str
    error: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/orders/place", response_model=ManualOrderResponse)
async def place_manual_order(payload: ManualOrderRequest):
    """
    Submit a manual order from the Dashboard to the appropriate broker.

    Routing rules (delegated to OrderRouter):
      - Futures (MES, MNQ, MCL, etc.)  → IBKR
      - Equities (SPY, QQQ, AAPL, ...) → Schwab
      - Options                          → Schwab (preferred), fallback IBKR
      - Spot crypto (BTCUSD, ETHUSD)    → CryptoMarketModule

    Returns a fill confirmation dict on success, or a 4xx/5xx error on failure.
    """
    if _order_router is None:
        raise HTTPException(
            status_code=503,
            detail="Order router not initialised — engine still starting up.",
        )

    # Map Dashboard direction field to the string the OrderRouter / IBKR expect
    action = "BUY" if payload.direction == "BUY" else "SELL"

    order_dict = {
        "symbol": payload.symbol,
        "action": action,
        "quantity": payload.quantity,
        "order_type": payload.order_type,
        "limit_price": payload.limit_price,
        # Stop-loss and take-profit are advisory metadata stored with the trade;
        # they are not sent to the broker as bracket orders in this phase.
        "stop_loss": payload.stop_loss,
        "take_profit": payload.take_profit,
        # Mark the origin so downstream logs can distinguish manual vs. algo orders
        "strategy": "manual_dashboard",
    }

    logger.info(
        "[MANUAL ORDER] %s %s %d contract(s) [%s]",
        action,
        payload.symbol,
        payload.quantity,
        payload.order_type,
    )

    try:
        result = await _order_router.route_order(order_dict)
    except RuntimeError as exc:
        # Broker not connected, etc.
        logger.error("[MANUAL ORDER] Routing failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[MANUAL ORDER] Unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Order execution error: {exc}") from exc

    fill_id = result.get("fill_id") or result.get("order_id")
    broker = result.get("broker", "unknown")
    status = result.get("status", "unknown")
    error = result.get("error")

    if status == "placed":
        message = (
            f"Order placed successfully via {broker.upper()}. "
            f"Fill ID: {fill_id or 'pending'}"
        )
        logger.info(
            "[MANUAL ORDER] ✅ %s %s %d — broker=%s fill_id=%s",
            action,
            payload.symbol,
            payload.quantity,
            broker,
            fill_id,
        )
    else:
        message = f"Order submission returned status '{status}'. Check logs for details."
        if error:
            message += f" Error: {error}"
        logger.warning(
            "[MANUAL ORDER] ⚠️ %s %s status=%s error=%s",
            action,
            payload.symbol,
            status,
            error,
        )

    return ManualOrderResponse(
        status=status,
        fill_id=str(fill_id) if fill_id else None,
        symbol=payload.symbol,
        action=action,
        quantity=payload.quantity,
        order_type=payload.order_type,
        broker=broker,
        message=message,
        error=error,
    )


@router.get("/orders/status")
async def get_order_router_status():
    """
    Return the current connectivity status of the OrderRouter.

    Reports which brokers are wired and available for order execution.
    """
    if _order_router is None:
        return {
            "status": "not_initialised",
            "ibkr_connected": False,
            "schwab_connected": False,
            "futures_broker": "unavailable",
            "equity_broker": "unavailable",
        }

    status = _order_router.status()
    status["status"] = "ok"
    return status
