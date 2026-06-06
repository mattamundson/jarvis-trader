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


def _parse_strategy_params(raw: Any) -> dict:
    """Deserialize strategy_params — SQLite returns JSON text, not a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


class ShadowModeTracker:
    """
    Logs 'would-be' trades to the database for performance comparison.
    Shadow trades are stored in the paper_trades table but marked as shadow.
    """

    def __init__(self, db_manager: Optional[DatabaseManager]):
        self._db = db_manager

    def set_db(self, db_manager: DatabaseManager) -> None:
        """Inject or replace the DB after construction (e.g. once the engine DB is ready)."""
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

        # Intentionally NO analyst_signals: shadow/validation trades must not
        # feed the live Brier/IC calibration surface (they are counterfactual).
        strategy_params = {
            "strategy_name": strategy_name,
            "is_shadow": True,
            "reasoning": reasoning,
            "original_quantity": quantity,
        }

        if self._db is None:
            logger.warning("[Shadow] No DB available — shadow entry not persisted")
            return ""

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
                strategy_params=strategy_params,
            )
            logger.info(f"[Shadow] Logged entry for {symbol} ({strategy_name}) at {price}")
            return shadow_id
        except Exception as exc:
            logger.error(f"[Shadow] Failed to log entry: {exc}")
            return ""

    def log_shadow_exit(
        self, shadow_id: str, exit_price: float, pnl: float, reason: str = "exit_signal"
    ) -> bool:
        """Close a shadow trade and record P&L."""
        if self._db is None:
            logger.warning("[Shadow] No DB available — shadow exit not persisted")
            return False

        try:
            success = self._db.close_paper_trade(
                trade_id=shadow_id,
                exit_price=exit_price,
                exit_time=datetime.now(timezone.utc).isoformat(),
                pnl=pnl,
            )
            if success:
                logger.info(f"[Shadow] Logged exit for {shadow_id} at {exit_price} pnl={pnl:+.2f}")
            return success
        except Exception as exc:
            logger.error(f"[Shadow] Failed to log exit for {shadow_id}: {exc}")
            return False

    def get_shadow_performance(self, strategy_name: Optional[str] = None) -> Dict[str, Any]:
        """Compute metrics for shadow trades."""
        _zero = {
            "count": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }

        if self._db is None:
            logger.warning("[Shadow] No DB available — returning zero metrics")
            return _zero

        trades = self._db.get_closed_trades(limit=1000)

        # Bug 1 fix: SQLite persists strategy_params as JSON text; deserialize before filtering.
        for t in trades:
            t["strategy_params"] = _parse_strategy_params(t.get("strategy_params"))

        shadow_trades = [t for t in trades if t["strategy_params"].get("is_shadow")]

        if strategy_name:
            shadow_trades = [
                t
                for t in shadow_trades
                if t["strategy_params"].get("strategy_name") == strategy_name
            ]

        if not shadow_trades:
            return _zero

        pnl_vals = [float(t.get("pnl", 0.0) or 0.0) for t in shadow_trades]
        wins = [p for p in pnl_vals if p > 0]
        losses = [p for p in pnl_vals if p < 0]

        return {
            "count": len(shadow_trades),
            "total_pnl": sum(pnl_vals),
            "win_rate": len(wins) / len(shadow_trades) if shadow_trades else 0.0,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
        }
