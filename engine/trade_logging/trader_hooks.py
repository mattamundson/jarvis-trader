"""
JARVIS TRADER — TraderAgent Integration with Trade Logging
===========================================================
Hooks to automatically capture trade decisions in the TraderAgent.decide() pipeline.

This module provides integration points for auto-logging trade entries and exits
without requiring manual logging steps in the API layer.

Usage:
  In TraderAgent.decide(), after returning a TradeDecision:
    await setup_trade_logging(db_manager)
    trade_decision = await trader.decide(...)
    trade_id = await log_trade_entry(
        symbol=symbol,
        trade_decision=trade_decision,
        debate_result=debate_result,
        analyst_reports=analyst_reports,
    )
    # Store trade_id for later exit logging
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from trade_logging.trade_logger import TradeLogger

logger = logging.getLogger("jarvis_trader.trade_logging.trader_hooks")

__all__ = ["setup_trade_logging", "log_trade_entry", "log_trade_exit"]

# Module-level TradeLogger instance
_trade_logger: Optional[TradeLogger] = None


def setup_trade_logging(db_manager: Any) -> None:
    """
    Initialize the module-level TradeLogger with a database manager.

    Call this once at application startup, ideally in the FastAPI lifespan.

    Args:
        db_manager: DatabaseManager instance
    """
    global _trade_logger
    if db_manager is None:
        logger.warning("[Hooks] Database manager is None — trade logging disabled")
        return
    _trade_logger = TradeLogger(db_manager)
    logger.info("[Hooks] Trade logging initialized")


async def log_trade_entry(
    symbol: str,
    trade_decision: Any,  # TradeDecision dataclass
    debate_result: dict,
    analyst_reports: dict,
) -> Optional[str]:
    """
    Log a trade entry with full decision context.

    Intended to be called from TraderAgent.decide() or the pipeline after
    a non-HOLD decision is made.

    Args:
        symbol: Trading symbol (e.g., "MCL", "MNQ")
        trade_decision: TradeDecision from TraderAgent.decide()
        debate_result: Bull/bear debate output dict
        analyst_reports: All analyst reports dict

    Returns:
        trade_id (UUID string) if successfully logged, None on error or if
        trade_logger not initialized
    """
    if _trade_logger is None:
        logger.debug(
            "[Hooks] Trade logger not initialized — entry not logged for %s",
            symbol,
        )
        return None

    trade_id = await _trade_logger.log_entry(
        symbol=symbol,
        trade_decision=trade_decision,
        debate_result=debate_result,
        analyst_reports=analyst_reports,
    )
    return trade_id


async def log_trade_exit(
    trade_id: str,
    exit_price: float,
    pnl: float,
    exit_time: Optional[str] = None,
) -> bool:
    """
    Log a trade exit with P&L.

    Intended to be called when a paper trade is closed (exit or stopped out).

    Args:
        trade_id: UUID of the trade being closed
        exit_price: Exit fill price
        pnl: Realized P&L in dollars
        exit_time: ISO-8601 exit time (defaults to now)

    Returns:
        True if exit was logged, False on error or if trade_logger not initialized
    """
    if _trade_logger is None:
        logger.debug("[Hooks] Trade logger not initialized — exit not logged")
        return False

    success = await _trade_logger.log_exit(
        trade_id=trade_id,
        exit_price=exit_price,
        pnl=pnl,
        exit_time=exit_time,
    )
    return success


async def correlate_entry_to_decision(
    trade_id: str,
    symbol: str,
    timestamp: str,
) -> bool:
    """
    Background task: correlate a trade entry to the decisions table.

    Finds the decision that led to this trade and links them in the
    trade_journal for full attribution.

    Args:
        trade_id: UUID of the trade
        symbol: Trading symbol
        timestamp: Trade entry timestamp (ISO-8601)

    Returns:
        True if correlation successful, False otherwise
    """
    if _trade_logger is None:
        logger.debug("[Hooks] Trade logger not initialized — correlation skipped")
        return False

    success = await _trade_logger.correlate_entry_to_decision(
        trade_id=trade_id,
        symbol=symbol,
        timestamp=timestamp,
    )
    return success
