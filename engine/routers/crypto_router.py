"""
Crypto router — expose Freqtrade/crypto module status via API.

Shapes match the dashboard /crypto page contracts. Every endpoint degrades to a
clean disabled/empty payload (never a 404 or 500) when the crypto module is off
or the Freqtrade bridge is unreachable, so the page renders an honest disabled
state rather than crashing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger("jarvis_trader.routers.crypto")

router = APIRouter(prefix="/crypto", tags=["crypto"])


def _get_module():
    try:
        from orchestrator import get_orchestrator

        orch = get_orchestrator()
        if orch:
            return orch.get_module("crypto")
    except Exception:
        pass
    return None


def _safe_bridge(module):
    """Return the Freqtrade bridge, or None. ``module._bridge`` raises
    AttributeError under a non-freqtrade backend (e.g. kraken), so guard it."""
    if module is None:
        return None
    try:
        return module._bridge
    except Exception:
        return None


@router.get("/status")
async def crypto_status():
    """Crypto module health in the dashboard's CryptoStatus shape."""
    module = _get_module()
    if not module or not module.is_enabled():
        return {
            "enabled": False,
            "connected": False,
            "freqtrade_running": False,
            "daily_pnl": 0.0,
            "open_positions_count": 0,
            "last_sync": None,
        }

    health = module.health_check()
    status_val = health.status.value if hasattr(health.status, "value") else str(health.status)
    connected = status_val in ("ok", "degraded", "paper")

    bridge = _safe_bridge(module)
    freqtrade_running = False
    if bridge is not None:
        try:
            freqtrade_running = await bridge.is_running()
        except Exception as exc:
            logger.debug("crypto_status: bridge.is_running failed: %s", exc)

    last_trade_at = getattr(health, "last_trade_at", None)
    return {
        "enabled": True,
        "connected": connected,
        "freqtrade_running": freqtrade_running,
        "daily_pnl": float(health.daily_pnl or 0.0),
        "open_positions_count": int(health.open_positions or 0),
        "last_sync": last_trade_at.isoformat() if hasattr(last_trade_at, "isoformat") else last_trade_at,
    }


@router.get("/positions")
async def crypto_positions():
    """Open crypto positions in the dashboard's CryptoPosition shape.

    Sourced from the bridge's native Freqtrade trade records (which carry
    pair/stake_amount/current_rate/profit), not the base Position mapping.
    """
    bridge = _safe_bridge(_get_module())
    if bridge is None:
        return {"positions": []}
    try:
        trades = await bridge.get_trades()
    except Exception as exc:
        logger.debug("crypto_positions: get_trades failed: %s", exc)
        return {"positions": []}

    positions = []
    for t in trades or []:
        profit_ratio = t.get("profit_ratio")
        profit_pct = (
            round(profit_ratio * 100, 4)
            if isinstance(profit_ratio, (int, float))
            else t.get("profit_pct")
        )
        positions.append(
            {
                "pair": t.get("pair"),
                "open_date": t.get("open_date"),
                "stake_amount": t.get("stake_amount"),
                "current_rate": t.get("current_rate"),
                "profit_pct": profit_pct,
                "profit_abs": t.get("profit_abs"),
            }
        )
    return {"positions": positions}


@router.get("/pnl")
async def crypto_pnl():
    """Today's crypto P&L plus cumulative total (CryptoPnL shape)."""
    module = _get_module()
    if not module or not module.is_enabled():
        return {"daily_pnl": 0.0, "total_pnl": 0.0, "target": 100.0, "progress_pct": 0.0}

    pnl = await module.get_daily_pnl()

    total_pnl = 0.0
    bridge = _safe_bridge(module)
    if bridge is not None:
        try:
            profit = await bridge.get_profit()
            total_pnl = float(
                profit.get("profit_closed_coin", profit.get("profit_all_coin", 0.0)) or 0.0
            )
        except Exception as exc:
            logger.debug("crypto_pnl: get_profit failed: %s", exc)

    return {
        "daily_pnl": pnl,
        "total_pnl": total_pnl,
        "target": module.daily_target,
        "progress_pct": round(pnl / module.daily_target * 100, 1) if module.daily_target else 0,
    }


@router.get("/freqtrade/status")
async def freqtrade_status():
    """Flat Freqtrade bot status (FreqtradeStatus shape).

    Merges the bridge's /ping, /show_config, /status and /profit into the flat
    object the dashboard reads. Fields that Freqtrade doesn't supply degrade to
    None/0 rather than erroring.
    """
    empty = {
        "running": False,
        "version": None,
        "state": None,
        "dry_run": None,
        "bot_name": None,
        "open_trade_count": 0,
        "profit_today_abs": 0.0,
    }
    bridge = _safe_bridge(_get_module())
    if bridge is None:
        return empty
    try:
        running = await bridge.is_running()
        config = await bridge.get_config()
        status = await bridge.get_status()
        profit = await bridge.get_profit()

        if isinstance(status, list):
            open_count = len(status)
        elif isinstance(status, dict):
            open_count = len(status.get("trades", []) or [])
        else:
            open_count = 0

        return {
            "running": running,
            "version": config.get("version"),
            "state": config.get("state"),
            "dry_run": config.get("dry_run"),
            "bot_name": config.get("bot_name"),
            "open_trade_count": open_count,
            "profit_today_abs": profit.get(
                "profit_today_abs", profit.get("profit_closed_coin", 0.0)
            ),
        }
    except Exception as exc:
        logger.debug("freqtrade_status failed: %s", exc)
        return {**empty, "error": str(exc)}


@router.post("/freqtrade/start")
async def freqtrade_start():
    """Start the Freqtrade trading loop via the bridge."""
    bridge = _safe_bridge(_get_module())
    if bridge is None:
        return {"ok": False, "action": "start", "message": "Crypto bridge not available"}
    try:
        ok = await bridge.start_trading()
        return {"ok": bool(ok), "action": "start"}
    except Exception as exc:
        return {"ok": False, "action": "start", "error": str(exc)}


@router.post("/freqtrade/stop")
async def freqtrade_stop():
    """Stop the Freqtrade trading loop via the bridge."""
    bridge = _safe_bridge(_get_module())
    if bridge is None:
        return {"ok": False, "action": "stop", "message": "Crypto bridge not available"}
    try:
        ok = await bridge.stop_trading()
        return {"ok": bool(ok), "action": "stop"}
    except Exception as exc:
        return {"ok": False, "action": "stop", "error": str(exc)}
