"""
JARVIS TRADER — Shadow Mode Framework
Tracks trade decisions from experimental strategies without taking real risk.
Implements the requirements from Phase 2 of the JARVIS Master Battle Plan.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database.manager import DatabaseManager

logger = logging.getLogger("jarvis_trader.shadow_mode")

class ShadowModeTracker:
    """
    Logs 'would-be' trades to the database for performance comparison.
    Shadow trades are stored in the paper_trades table but marked as shadow.
    """

    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager

    def log_shadow_entry(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        strategy_name: str,
        reasoning: str = "",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> str:
        """Log a shadow entry and return the shadow_trade_id."""
        shadow_id = f"shadow_{uuid.uuid4().hex[:8]}"

        strategy_params = {
            "strategy_name": strategy_name,
            "is_shadow": True,
            "reasoning": reasoning,
            "original_quantity": quantity
        }

        try:
            self._db.insert_paper_trade(
                trade_id=shadow_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=price,
                entry_time=datetime.now(timezone.utc).isoformat(),
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy_params=strategy_params
            )
            logger.info(f"[Shadow] Logged entry for {symbol} ({strategy_name}) at {price}")
            return shadow_id
        except Exception as exc:
            logger.error(f"[Shadow] Failed to log entry: {exc}")
            return ""

    def log_shadow_exit(
        self,
        shadow_id: str,
        exit_price: float,
        pnl: float,
        reason: str = "exit_signal"
    ) -> bool:
        """Close a shadow trade and record P&L."""
        try:
            success = self._db.close_paper_trade(
                trade_id=shadow_id,
                exit_price=exit_price,
                exit_time=datetime.now(timezone.utc).isoformat(),
                pnl=pnl
            )
            if success:
                logger.info(f"[Shadow] Logged exit for {shadow_id} at {exit_price} pnl={pnl:+.2f}")
            return success
        except Exception as exc:
            logger.error(f"[Shadow] Failed to log exit for {shadow_id}: {exc}")
            return False

    def get_shadow_performance(self, strategy_name: Optional[str] = None) -> Dict[str, Any]:
        """Compute metrics for shadow trades."""
        trades = self._db.get_closed_trades(limit=1000)
        shadow_trades = [
            t for t in trades 
            if isinstance(t.get("strategy_params"), dict) and t["strategy_params"].get("is_shadow")
        ]

        if strategy_name:
            shadow_trades = [
                t for t in shadow_trades 
                if t["strategy_params"].get("strategy_name") == strategy_name
            ]

        if not shadow_trades:
            return {"count": 0, "total_pnl": 0.0}

        pnl_vals = [float(t.get("pnl", 0.0) or 0.0) for t in shadow_trades]
        wins = [p for p in pnl_vals if p > 0]

        return {
            "count": len(shadow_trades),
            "total_pnl": sum(pnl_vals),
            "win_rate": len(wins) / len(shadow_trades) if shadow_trades else 0.0,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum([p for p in pnl_vals if p < 0]) / (len(pnl_vals) - len(wins)) if (len(pnl_vals) - len(wins)) > 0 else 0.0
        }
