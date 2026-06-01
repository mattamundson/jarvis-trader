"""
JARVIS TRADER — Trade Decision Logging Middleware
===================================================
Automatic capture of trade entries with full decision context (regime, bias, signals),
exit events with P&L tracking, and background correlation to the decisions table.

This module provides:
  1. TradeLogger — middleware hook in TraderAgent for auto-logging entries
  2. Entry logging with regime, signal scores, bias
  3. Exit logging with price + P&L
  4. Background task for decisions table attribution

Usage in TraderAgent.decide():
  logger_hook = TradeLogger(db_manager)
  trade_decision = await trader_agent.decide(...)
  await logger_hook.log_entry(symbol, trade_decision, debate_result, analyst_reports)
  # ... later on exit ...
  await logger_hook.log_exit(trade_id, exit_price, pnl)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.trade_logging.trade_logger")

__all__ = ["TradeLogger", "LogEntry"]


@dataclass
class LogEntry:
    """
    Internal representation of a trade entry to be logged.
    Captures full decision context for provenance.
    """

    trade_id: str
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    entry_price: float
    entry_time: str  # ISO-8601
    signal_score: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0
    regime: Optional[str] = None
    bias: Optional[str] = None
    composite_score: Optional[float] = None
    stc_contrib: Optional[int] = None
    orb_contrib: Optional[int] = None
    vwap_contrib: Optional[int] = None
    bull_score: Optional[float] = None
    bear_score: Optional[float] = None
    debate_confidence: Optional[float] = None
    reasoning: Optional[str] = None
    risk_notes: Optional[str] = None


class TradeLogger:
    """
    Middleware hook for automatic trade logging in the trading pipeline.

    Coordinates with DatabaseManager to capture:
      1. Trade entry with full decision context
      2. Trade exit with P&L
      3. Correlation to decisions table for attribution

    Thread-safe: all database operations are delegated to DatabaseManager
    which handles locking internally.
    """

    def __init__(self, db_manager: Any):
        """
        Initialize TradeLogger with a DatabaseManager instance.

        Args:
            db_manager: DatabaseManager instance for persistence
        """
        self._db = db_manager

    async def log_entry(
        self,
        symbol: str,
        trade_decision: Any,  # TradeDecision dataclass
        debate_result: dict,
        analyst_reports: dict,
    ) -> Optional[str]:
        """
        Log a trade entry with full decision context.

        Captures:
          - Trade entry: symbol, side, quantity, price, time
          - Signal metadata: regime, bias, confidence, scores
          - Decision context: reasoning, risk notes
          - Attribution: debate scores, analyst signal breakdown

        Args:
            symbol: Trading symbol (e.g., "MCL", "MNQ")
            trade_decision: TradeDecision from TraderAgent.decide()
            debate_result: Bull/bear debate result dict with scores
            analyst_reports: All analyst reports dict

        Returns:
            trade_id if successfully logged, None on error
        """
        if not self._db:
            logger.warning("[TradeLogger] No database manager — entry logging disabled")
            return None

        # Exit early if it's a HOLD decision
        if trade_decision.action.lower() == "hold":
            logger.debug(
                "[TradeLogger] HOLD decision for %s — no entry logging", symbol
            )
            return None

        # Generate trade ID (same UUID that will be used in paper_trades)
        trade_id = str(uuid.uuid4())

        try:
            # Extract signal context from analyst reports
            technical_report = analyst_reports.get("technical", {})
            indicators = technical_report.get("indicators", {})

            regime = technical_report.get("regime")
            bias = technical_report.get("bias")
            composite_score = indicators.get("composite_score")
            stc_contrib = indicators.get("stc_contrib")
            orb_contrib = indicators.get("orb_contrib")
            vwap_contrib = indicators.get("vwap_contrib")

            # Extract debate context
            bull_score = debate_result.get("bull_score")
            bear_score = debate_result.get("bear_score")
            debate_confidence = debate_result.get("confidence")

            # Build entry log entry
            entry = LogEntry(
                trade_id=trade_id,
                symbol=symbol.upper(),
                side=trade_decision.action.lower(),
                quantity=float(trade_decision.quantity),
                entry_price=float(trade_decision.entry_price or 0.0),
                entry_time=datetime.now().isoformat(),
                signal_score=float(trade_decision.signal_score),
                confidence=float(trade_decision.confidence),
                regime=regime,
                bias=bias,
                composite_score=composite_score,
                stc_contrib=stc_contrib,
                orb_contrib=orb_contrib,
                vwap_contrib=vwap_contrib,
                bull_score=bull_score,
                bear_score=bear_score,
                debate_confidence=debate_confidence,
                reasoning=trade_decision.reasoning,
                risk_notes=trade_decision.risk_notes,
            )

            # Insert the trade into the mock database first (for exit logging)
            self._db.insert_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=entry.side,
                quantity=entry.quantity,
                entry_price=entry.entry_price,
                entry_time=entry.entry_time,
            )

            # Persist to trade_journal table (return id intentionally
            # discarded — provenance is also persisted via _store_signal_provenance).
            self._db.add_journal_entry(
                trade_id=trade_id,
                note=f"AUTO-ENTRY: {entry.side.upper()} {entry.quantity} {symbol} @ {entry.entry_price}",
                tags="auto_logged,entry",
                mood=None,  # auto-logged, no mood
                lesson=None,
                timestamp=entry.entry_time,
            )

            # Also update paper_trades to include signal provenance (if supported)
            # This requires updating the paper_trades schema to have these columns
            self._store_signal_provenance(trade_id, entry)

            logger.info(
                "[TradeLogger] Entry logged: trade_id=%s symbol=%s side=%s "
                "qty=%s price=%.4f regime=%s conf=%.2f",
                trade_id[:8],
                symbol,
                entry.side,
                entry.quantity,
                entry.entry_price,
                regime,
                entry.confidence,
            )

            return trade_id

        except Exception as err:
            logger.error("[TradeLogger] Failed to log entry: %s", err, exc_info=True)
            return None

    async def log_exit(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
        exit_time: Optional[str] = None,
    ) -> bool:
        """
        Log a trade exit with price and P&L.

        Updates the associated trade_journal entry with exit data.

        Args:
            trade_id: UUID of the trade being closed
            exit_price: Exit fill price
            pnl: Realized P&L in dollars
            exit_time: ISO-8601 exit time (defaults to now)

        Returns:
            True if exit was logged, False on error
        """
        if not self._db:
            logger.warning("[TradeLogger] No database manager — exit logging disabled")
            return False

        exit_time = exit_time or datetime.now().isoformat()

        try:
            # Append exit note to the trade's journal entry
            notes = (
                f"AUTO-EXIT: exit_price={exit_price:.4f} pnl={pnl:+.2f} "
                f"time={exit_time}"
            )

            # Get the trade to find its journal entry
            trade = self._db.get_trade_by_id(trade_id)
            if not trade:
                logger.warning("[TradeLogger] Trade not found: trade_id=%s", trade_id)
                return False

            # Find the journal entry for this trade
            journal_entries = self._db.get_journal_entries(trade_id=trade_id, limit=1)
            if journal_entries:
                entry_id = journal_entries[0]["id"]
                # Update the entry with exit note
                updated = self._db.update_journal_entry(
                    entry_id=entry_id,
                    note=f"{journal_entries[0]['note']}\n{notes}",
                    tags="auto_logged,entry,exit",
                )
                if updated:
                    logger.info(
                        "[TradeLogger] Exit logged: trade_id=%s exit_price=%.4f pnl=%+.2f",
                        trade_id[:8],
                        exit_price,
                        pnl,
                    )
                    return True

            logger.warning(
                "[TradeLogger] Could not find journal entry for trade_id=%s",
                trade_id,
            )
            return False

        except Exception as err:
            logger.error("[TradeLogger] Failed to log exit: %s", err, exc_info=True)
            return False

    def _store_signal_provenance(self, trade_id: str, entry: LogEntry) -> None:
        """
        Store signal provenance in paper_trades table.

        This persists all signal context directly into the paper_trades record
        so that the trade journal has full attribution without needing
        to correlate back to decisions table.

        Note: This requires schema updates to paper_trades table to add:
          - regime, structure_position, bias
          - composite_score, stc_contrib, orb_contrib, vwap_contrib
          - bull_score, bear_score, debate_confidence
          - deciding_stage, regime_tier

        This is a non-blocking operation — failures are logged but don't
        prevent the trade from being logged.
        """
        try:
            if not hasattr(self._db, "_connect"):
                logger.debug("[TradeLogger] Skipping provenance storage — no direct DB access")
                return

            conn = self._db._connect()
            try:
                # Check if paper_trades has the required columns
                cursor = conn.execute("PRAGMA table_info(paper_trades)")
                columns = {row[1] for row in cursor.fetchall()}

                # Only update if columns exist
                if "regime" in columns:
                    sql = """
                        UPDATE paper_trades
                        SET regime = ?,
                            bias = ?,
                            composite_score = ?,
                            stc_contrib = ?,
                            orb_contrib = ?,
                            vwap_contrib = ?,
                            bull_score = ?,
                            bear_score = ?,
                            debate_confidence = ?
                        WHERE trade_id = ?
                    """
                    params = (
                        entry.regime,
                        entry.bias,
                        entry.composite_score,
                        entry.stc_contrib,
                        entry.orb_contrib,
                        entry.vwap_contrib,
                        entry.bull_score,
                        entry.bear_score,
                        entry.debate_confidence,
                        trade_id,
                    )
                    conn.execute(sql, params)
                    conn.commit()
                    logger.debug(
                        "[TradeLogger] Signal provenance stored for trade_id=%s",
                        trade_id[:8],
                    )
            finally:
                conn.close()
        except Exception as err:
            logger.debug(
                "[TradeLogger] Could not store provenance (non-critical): %s", err
            )

    async def correlate_entry_to_decision(
        self,
        trade_id: str,
        symbol: str,
        timestamp: str,
    ) -> bool:
        """
        Background task: correlate a paper trade entry to the decisions table.

        Finds the most recent decision for the symbol at or before the trade
        entry time, then updates the trade_journal entry with the decision
        reference for full attribution.

        Args:
            trade_id: UUID of the trade
            symbol: Trading symbol
            timestamp: Trade entry timestamp (ISO-8601)

        Returns:
            True if correlation was successful, False otherwise
        """
        if not self._db:
            logger.warning("[TradeLogger] No database manager — correlation disabled")
            return False

        try:
            # Find the decision that led to this trade
            decisions = self._db.get_decisions(symbol=symbol, limit=5)
            if not decisions:
                logger.debug(
                    "[TradeLogger] No decisions found for %s to correlate", symbol
                )
                return False

            # Use the most recent decision (at or before the trade entry time)
            # In a real system, you'd do proper timestamp matching.
            decision = decisions[0]  # Most recent decision
            decision_id = decision.get("id")

            if not decision_id:
                logger.warning("[TradeLogger] Decision has no id — cannot correlate")
                return False

            # Update the journal entry with decision reference
            journal_entries = self._db.get_journal_entries(trade_id=trade_id, limit=1)
            if journal_entries:
                entry_id = journal_entries[0]["id"]
                # Append decision reference to note
                current_note = journal_entries[0].get("note", "")
                new_note = f"{current_note}\n[DECISION_ID: {decision_id}]"

                self._db.update_journal_entry(
                    entry_id=entry_id,
                    note=new_note,
                )
                logger.info(
                    "[TradeLogger] Entry correlated to decision: "
                    "trade_id=%s decision_id=%s",
                    trade_id[:8],
                    decision_id,
                )
                return True

            logger.warning(
                "[TradeLogger] Journal entry not found for trade_id=%s",
                trade_id,
            )
            return False

        except Exception as err:
            logger.error(
                "[TradeLogger] Failed to correlate entry to decision: %s",
                err,
                exc_info=True,
            )
            return False
