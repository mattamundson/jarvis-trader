"""
JARVIS TRADER — TradingView Webhook Router
==========================================
Receives inbound webhook signals from TradingView and forwards them to the
trading pipeline via a registered callback.

Routes
------
GET  /webhook/tradingview/test     — Liveness probe
POST /webhook/tradingview          — Receive signal payload
GET  /webhook/dedup-stats          — Deduplication cache stats

Usage in main.py
-----------------
    from routers.webhook_router import router as webhook_router, set_pipeline_callback, get_recent_webhooks
    app.include_router(webhook_router)
    set_pipeline_callback(my_async_callback)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.webhook")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Shared secret for validating inbound payloads (empty = disabled)
WEBHOOK_SECRET: str = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "")

# Registered async callback — set by main.py after pipeline is ready
_pipeline_callback: Optional[Callable[..., Awaitable[dict]]] = None

# Ring buffer: most recent webhook payloads (capped at 50)
_recent_webhooks: list[dict] = []
_RECENT_MAX = 50

# ---------------------------------------------------------------------------
# Webhook deduplication cache: key -> timestamp
# Rejects identical {symbol}:{action}:{price} within 30 seconds
# ---------------------------------------------------------------------------
_dedup_cache: dict[str, float] = {}
_DEDUP_WINDOW = 30.0  # seconds


def _is_duplicate(symbol: str, action: str, price: float | None) -> bool:
    """Return True if an identical webhook was received within the dedup window."""
    import time

    now = time.time()
    key = f"{symbol.upper()}:{action.upper()}:{round(price or 0, 2)}"

    last_seen = _dedup_cache.get(key)
    if last_seen and (now - last_seen) < _DEDUP_WINDOW:
        return True

    _dedup_cache[key] = now

    # Prune old entries (keep cache small)
    expired = [k for k, ts in _dedup_cache.items() if now - ts > _DEDUP_WINDOW * 2]
    for k in expired:
        del _dedup_cache[k]

    return False


# ---------------------------------------------------------------------------
# Public helpers called from main.py
# ---------------------------------------------------------------------------


def set_pipeline_callback(cb: Callable[..., Awaitable[dict]]) -> None:
    """Register the async function to call when a valid signal arrives."""
    global _pipeline_callback
    _pipeline_callback = cb


def get_recent_webhooks(limit: int = 20) -> list[dict]:
    """Return up to *limit* most-recent webhook payloads (newest first)."""
    return list(reversed(_recent_webhooks[-limit:]))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TradingViewPayload(BaseModel):
    """Inbound webhook payload from a TradingView alert."""

    symbol: str
    action: str  # LONG | SHORT | CLOSE | HOLD
    price: Optional[float] = None
    timeframe: Optional[str] = None
    indicator: Optional[str] = None
    os_value: Optional[float] = None
    atr: Optional[float] = None
    regime: Optional[str] = None
    secret: Optional[str] = None  # Optional webhook secret
    # Accept arbitrary extra fields from custom alert messages
    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["webhook"])

_VALID_ACTIONS = {"LONG", "SHORT", "CLOSE", "HOLD"}


@router.get("/webhook/tradingview/test")
async def webhook_test():
    """Liveness probe — confirms the webhook endpoint is reachable."""
    return {
        "status": "ok",
        "message": "TradingView webhook endpoint is live",
        "secret_configured": bool(WEBHOOK_SECRET),
    }


@router.post("/webhook/tradingview")
async def receive_tradingview_webhook(payload: TradingViewPayload):
    """
    Receive a TradingView alert and forward it to the trading pipeline.

    Validation order:
    1. Optional shared-secret check (if TRADINGVIEW_WEBHOOK_SECRET is set)
    2. Action must be one of LONG / SHORT / CLOSE / HOLD
    3. Deduplication — identical {symbol:action:price} within 30 s → rejected
    4. HOLD signals are acknowledged but do NOT trigger the pipeline
    5. All other signals are forwarded to the registered pipeline callback
    """
    # ── 1. Secret validation ───────────────────────────────────────────────
    if WEBHOOK_SECRET:
        if payload.secret != WEBHOOK_SECRET:
            raise HTTPException(
                status_code=403,
                detail="Invalid or missing webhook secret",
            )

    symbol = payload.symbol.upper().strip()
    action = payload.action.upper().strip()
    price = payload.price

    # ── 2. Action validation ───────────────────────────────────────────────
    if action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {action!r}. Must be one of {sorted(_VALID_ACTIONS)}",
        )

    # ── 3. Deduplication check ─────────────────────────────────────────────
    if _is_duplicate(symbol, action, price):
        logger.warning("Duplicate webhook rejected: %s %s @ %s", symbol, action, price)
        return {
            "status": "duplicate",
            "symbol": symbol,
            "action": action,
            "message": "Duplicate webhook rejected (same signal within 30s window)",
        }

    # ── Record in ring buffer ──────────────────────────────────────────────
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "action": action,
        "price": price,
        "timeframe": payload.timeframe,
        "indicator": payload.indicator,
        "regime": payload.regime,
        "atr": payload.atr,
    }
    _recent_webhooks.append(record)
    if len(_recent_webhooks) > _RECENT_MAX:
        _recent_webhooks.pop(0)

    logger.info("Webhook received: %s %s @ %s", symbol, action, price)

    # ── 4. HOLD — acknowledge without triggering pipeline ─────────────────
    if action == "HOLD":
        return {
            "status": "received",
            "symbol": symbol,
            "action": action,
            "pipeline_triggered": False,
            "message": "HOLD signal acknowledged — no pipeline action taken",
        }

    # ── 5. Forward to pipeline callback ───────────────────────────────────
    if _pipeline_callback is None:
        return {
            "status": "received",
            "symbol": symbol,
            "action": action,
            "pipeline_triggered": False,
            "message": "Pipeline not initialized — signal queued for logging only",
        }

    try:
        result = await _pipeline_callback(
            symbol=symbol,
            action=action,
            price=price,
            timeframe=payload.timeframe,
            indicator=payload.indicator,
            os_value=payload.os_value,
            atr=payload.atr,
            regime=payload.regime,
        )
        return {
            "status": (
                result.get("status", "completed") if isinstance(result, dict) else "completed"
            ),
            "symbol": symbol,
            "action": action,
            "pipeline_triggered": True,
            "result": result,
        }
    except Exception as exc:
        logger.error("Pipeline callback raised: %s", exc, exc_info=True)
        return {
            "status": "error",
            "symbol": symbol,
            "action": action,
            "pipeline_triggered": False,
            "error": str(exc),
        }


@router.get("/webhook/dedup-stats")
async def get_dedup_stats():
    """Get current dedup cache stats."""
    import time

    now = time.time()
    active = {k: round(now - ts, 1) for k, ts in _dedup_cache.items() if now - ts < _DEDUP_WINDOW}
    return {
        "active_entries": len(active),
        "window_seconds": _DEDUP_WINDOW,
        "entries": active,
    }


@router.get("/signals/stats")
async def signals_stats():
    """Return webhook signal statistics including deduplication cache size."""
    recent = get_recent_webhooks(limit=50)
    return {
        "total_received": len(recent),
        "recent_webhooks": recent[:10],
        "dedup_cache_size": len(_dedup_cache),
    }
