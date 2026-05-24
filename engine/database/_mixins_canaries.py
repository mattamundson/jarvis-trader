"""
JARVIS TRADER — Canary Strategies Mixin
========================================
Database access for Phase 7.3 A/B Canary Framework.
Tracks strategies promoted from the discovery loop to live shadow testing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.database.canaries")

class CanariesMixin:
    """
    Mixin for managing the canary_strategies table.
    """

    def insert_canary_strategy(self, data: Dict[str, Any]) -> int:
        """
        Register a new canary strategy for trial.
        """
        sql = """
            INSERT INTO canary_strategies (
                strategy_file, symbol, interval, status, baseline_pf,
                start_time, end_time, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            data["strategy_file"],
            data["symbol"],
            data["interval"],
            data.get("status", "active"),
            data["baseline_pf"],
            data["start_time"],
            data["end_time"],
            json.dumps(data.get("metadata", {})),
            datetime.now(timezone.utc).isoformat()
        )
        return self.execute(sql, params)

    def get_active_canaries(self) -> List[Dict[str, Any]]:
        """Return all canaries currently in trial."""
        sql = "SELECT * FROM canary_strategies WHERE status = 'active'"
        return self.fetch_all(sql)

    def update_canary_performance(self, canary_id: int, live_pf: float, num_trades: int) -> int:
        """Update the live performance metrics for a canary."""
        sql = "UPDATE canary_strategies SET live_pf = ?, num_trades = ? WHERE id = ?"
        return self.execute(sql, (live_pf, num_trades, canary_id))

    def close_canary_trial(self, canary_id: int, status: str, actual_end_time: str) -> int:
        """Finalize a canary trial (passed/failed)."""
        sql = "UPDATE canary_strategies SET status = ?, actual_end_time = ? WHERE id = ?"
        return self.execute(sql, (status, actual_end_time, canary_id))

    def get_canary_by_file(self, strategy_file: str) -> Optional[Dict[str, Any]]:
        """Retrieve canary details by filename."""
        sql = "SELECT * FROM canary_strategies WHERE strategy_file = ?"
        return self.fetch_one(sql, (strategy_file,))
