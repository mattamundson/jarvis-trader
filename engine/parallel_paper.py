"""
JARVIS TRADER — Parallel Paper Trade Emitter
=============================================
When ENABLE_PARALLEL_PAPER=1, every paper-order submission is dual-emitted:

  Account A — uses production config from TradingConfig / engine/.env
  Account B — uses challenger overrides from config_challenger.get_challenger_config()

When the flag is 0 (default), single-emit with account_id='A' exactly as before.

This module is a thin shim.  It does NOT change the core PortfolioTracker or
SafetyLayer logic.  It calls insert_trade twice (or once) on the db_manager
with different account_id tags, then returns the production (A) trade_id so the
rest of the pipeline continues unchanged.

Safety invariants
-----------------
- Only called from paper-order submission paths.
- LIVE_TRADING_ENABLED must be False for this to be active (checked by caller).
- No duplicate position risk: Account B rows are tagged separately; the
  PortfolioTracker in-memory state tracks only Account A trades.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.parallel_paper")


def _enabled() -> bool:
    """Return True iff ENABLE_PARALLEL_PAPER=1."""
    return os.environ.get("ENABLE_PARALLEL_PAPER", "0") == "1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dual_emit_paper_trade(
    *,
    db_manager: Any,
    trade_id: str,
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    entry_time: Optional[str] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    strategy_params: Optional[Dict[str, Any]] = None,
    challenger_overrides: Optional[Dict[str, Any]] = None,
    safety_layer: Optional[Any] = None,
) -> str:
    """
    Emit one or two paper-trade rows depending on ENABLE_PARALLEL_PAPER.

    Parameters
    ----------
    db_manager:
        DatabaseManager instance with an ``insert_trade`` method.
    trade_id:
        The UUID already assigned to the Account A trade.
    symbol, side, quantity, entry_price, entry_time, stop_loss, take_profit:
        Standard trade fields; passed through unchanged to both rows.
    strategy_params:
        JSON-serialisable dict appended to both rows (identical for A and B).
    challenger_overrides:
        The dict returned by get_challenger_config().  Stored in the B row's
        strategy_params so analysts can see which config was active.
    safety_layer:
        Optional SafetyLayer instance.  When provided AND ENABLE_PARALLEL_PAPER=1,
        each account's per-account kill state is checked before emission.  If an
        account is halted, its trade row is skipped and the other account is NOT
        affected.  When None, halting is not checked (pre-migration behaviour).

    Returns
    -------
    str
        The Account A trade_id (same as the ``trade_id`` argument).  The
        Account B trade_id is logged but not returned; the rest of the
        pipeline has no need to reference it.
    """
    entry_time = entry_time or _utcnow()

    # ── Account A — always written unless per-account kill is active ──────────
    a_halted = False
    if _enabled() and safety_layer is not None:
        try:
            a_halted = safety_layer.is_account_halted("A")
        except Exception as _exc:
            logger.warning("[parallel_paper] is_account_halted('A') raised: %s", _exc)

    if a_halted:
        logger.warning(
            "[parallel_paper] Account A halted — skipping emission for trade %s symbol=%s",
            trade_id[:8],
            symbol,
        )
    else:
        _write_trade(
            db_manager=db_manager,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=entry_time,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_params=strategy_params,
            account_id="A",
        )

    # ── Account B — written only when parallel testing is enabled ─────────────
    if _enabled():
        b_halted = False
        if safety_layer is not None:
            try:
                b_halted = safety_layer.is_account_halted("B")
            except Exception as _exc:
                logger.warning("[parallel_paper] is_account_halted('B') raised: %s", _exc)

        if b_halted:
            logger.warning(
                "[parallel_paper] Account B halted — skipping emission symbol=%s",
                symbol,
            )
        else:
            b_trade_id = str(uuid.uuid4())
            b_params: Dict[str, Any] = dict(strategy_params or {})
            if challenger_overrides:
                b_params["_challenger_overrides"] = challenger_overrides
            _write_trade(
                db_manager=db_manager,
                trade_id=b_trade_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                entry_time=entry_time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy_params=b_params,
                account_id="B",
            )
            logger.debug(
                "[parallel_paper] dual-emit: A=%s B=%s symbol=%s",
                trade_id[:8],
                b_trade_id[:8],
                symbol,
            )

    return trade_id


def _write_trade(
    *,
    db_manager: Any,
    trade_id: str,
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    entry_time: str,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    strategy_params: Optional[Dict[str, Any]],
    account_id: str,
) -> None:
    """
    Write a single paper_trade row via db_manager.insert_trade.

    Passes account_id as a kwarg; DatabaseManager.insert_trade accepts it
    after migration_027 adds the column.  Falls back gracefully if the
    method signature does not yet include account_id (pre-migration DBs).
    """
    import inspect

    sig = inspect.signature(db_manager.insert_trade)
    has_account_id = "account_id" in sig.parameters

    kwargs: Dict[str, Any] = {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_time": entry_time,
        "status": "open",
        "notes": "",
    }

    # Merge stop_loss / take_profit into strategy_params for storage.
    merged: Dict[str, Any] = dict(strategy_params or {})
    if stop_loss is not None:
        merged["stop_loss"] = stop_loss
    if take_profit is not None:
        merged["take_profit"] = take_profit
    kwargs["strategy_params"] = merged if merged else None

    if has_account_id:
        kwargs["account_id"] = account_id

    db_manager.insert_trade(**kwargs)
