"""Local paper-ledger fill from a pipeline result.

Used by the market-open 1h scan so a BUY/SELL is recorded in ``paper_trades``
even though that scan currently only logs ``pipeline_runs``.

This path is ledger-only:
- it never calls ``safety_layer.check_order`` or ``submit_entry_with_stop``
- it never reads or writes ``ALLOW_PAPER_SIMULATED_ORDERS``
- it never places a broker order

Those broker gates stay off until a dedicated [safety-review] PR.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("jarvis_trader.paper.local_ledger")

_DIRECTIONAL = frozenset({"buy", "sell"})


def _halted(symbol: str) -> bool:
    try:
        from backtest.paper_config import PAPER_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError:  # pragma: no cover
        from engine.backtest.paper_config import PAPER_CONFIGS
        from engine.backtest.signals import DO_NOT_TRADE_SYMBOLS

    if symbol in DO_NOT_TRADE_SYMBOLS:
        return True
    cfg = PAPER_CONFIGS.get(symbol)
    return cfg is not None and not cfg.get("enabled", True)


def _kill_switch_active(safety_layer: Any) -> bool:
    if safety_layer is None:
        return False
    try:
        status = safety_layer.get_status() or {}
        return bool(status.get("kill_switch_active"))
    except Exception:
        try:
            return bool(getattr(safety_layer, "kill_switch_active", False))
        except Exception:
            return False


def maybe_log_local_paper_fill(
    *,
    symbol: str,
    result: dict,
    paper_tracker: Any,
    safety_layer: Any = None,
    live_trading_enabled: bool = False,
    source: str = "market_open_1h",
) -> dict:
    """Write one local paper_trades row when the result is a complete directional fill.

    Returns a dict with ``executed`` (bool) and ``reason`` (str). Never raises to
    the market-open loop: a ledger failure must not abort the scan.
    """
    action = str(result.get("final_action") or "hold").lower()
    if action not in _DIRECTIONAL:
        return {"executed": False, "reason": "not_directional"}

    if live_trading_enabled:
        logger.critical(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=live_trading_enabled",
            symbol,
            action,
        )
        return {"executed": False, "reason": "live_trading_enabled"}

    if paper_tracker is None:
        logger.warning(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=paper_tracker_missing",
            symbol,
            action,
        )
        return {"executed": False, "reason": "paper_tracker_missing"}

    if _kill_switch_active(safety_layer):
        logger.warning(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=kill_switch_active",
            symbol,
            action,
        )
        return {"executed": False, "reason": "kill_switch_active"}

    if _halted(symbol):
        logger.critical(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=symbol_halted",
            symbol,
            action,
        )
        return {"executed": False, "reason": "symbol_halted"}

    trade_dec = result.get("trade_decision") or {}
    entry_price = trade_dec.get("entry_price") or trade_dec.get("limit_price")
    stop_price = trade_dec.get("stop_price")
    if entry_price is None:
        logger.warning(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=missing_entry_price",
            symbol,
            action,
        )
        return {"executed": False, "reason": "missing_entry_price"}
    if stop_price is None:
        logger.critical(
            "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=missing_stop",
            symbol,
            action,
        )
        return {"executed": False, "reason": "missing_stop"}

    quantity = result.get("final_quantity") or trade_dec.get("quantity") or 1
    target_price = (
        trade_dec.get("target_1")
        or trade_dec.get("target_price")
        or trade_dec.get("take_profit")
        or trade_dec.get("target_2")
        or None
    )
    technical = (result.get("analyst_reports") or {}).get("technical") or {}
    fund = result.get("fund_decision") or {}
    conviction = fund.get("final_conviction") or trade_dec.get("confidence") or result.get("confidence") or 0.0

    try:
        open_for_symbol = [
            p
            for p in (paper_tracker.get_open_positions() or [])
            if str(p.get("symbol") or "").upper() == str(symbol).upper()
        ]
        if open_for_symbol:
            logger.info(
                "[LOCAL_LEDGER] symbol=%s action=%s executed=False reason=paper_position_already_open",
                symbol,
                action,
            )
            return {"executed": False, "reason": "paper_position_already_open"}
    except Exception as exc:
        logger.warning("[LOCAL_LEDGER] open-position check failed for %s: %s", symbol, exc)

    try:
        trade_id = paper_tracker.add_paper_trade(
            symbol=symbol,
            side=action,
            quantity=float(quantity),
            entry_price=float(entry_price),
            stop_loss=float(stop_price),
            take_profit=float(target_price) if target_price is not None else None,
            strategy_params={
                "source": source,
                "conviction": round(float(conviction), 4),
                "direction": action.upper(),
                "summary": result.get("summary", ""),
                "regime": technical.get("regime") or "unknown",
            },
        )
    except Exception as exc:
        logger.error("[LOCAL_LEDGER] add_paper_trade failed for %s: %s", symbol, exc)
        return {"executed": False, "reason": "ledger_write_failed"}

    logger.info(
        "[LOCAL_LEDGER] symbol=%s action=%s executed=True reason=local_ledger trade_id=%s",
        symbol,
        action,
        str(trade_id)[:8],
    )
    return {"executed": True, "reason": "local_ledger", "trade_id": trade_id}
