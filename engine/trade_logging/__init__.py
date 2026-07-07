"""
JARVIS TRADER — Trade Decision Logging Module
==============================================
Automated capture of trade entries and exits with full decision context,
including regime, bias, signal scores, and correlation to the decisions table.

Public API
----------
From trade_logger.py:
  - TradeLogger: Middleware for auto-logging trades
  - LogEntry: Data class for entry context

From trader_hooks.py:
  - setup_trade_logging(): Initialize at startup
  - log_trade_entry(): Auto-log entry with decision context
  - log_trade_exit(): Auto-log exit with P&L
  - correlate_entry_to_decision(): Background correlation task

Architecture
------------
1. TradeLogger receives TradeDecision from TraderAgent
2. Extracts signal context (regime, bias, scores) from analyst reports
3. Logs entry to trade_journal with full provenance
4. Updates paper_trades with signal context (regime, bias, composite_score, etc.)
5. On exit, logs P&L and correlates to decisions table

This eliminates manual logging and ensures every trade has full attribution
from decision through exit.
"""

from trade_logging.trade_logger import LogEntry, TradeLogger
from trade_logging.trader_hooks import (
    correlate_entry_to_decision,
    log_trade_entry,
    log_trade_exit,
    setup_trade_logging,
)

__all__ = [
    "TradeLogger",
    "LogEntry",
    "setup_trade_logging",
    "log_trade_entry",
    "log_trade_exit",
    "correlate_entry_to_decision",
]
