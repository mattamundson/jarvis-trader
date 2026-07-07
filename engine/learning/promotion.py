"""
JARVIS TRADER — Strategy Promotion Engine
Evaluates performance of shadow strategies and agents to promote them to live status.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("jarvis_trader.promotion")

# Use the same DB as agent feedback for consistency
DB_PATH = Path(__file__).parent.parent / "data" / "agent_feedback.db"


class PromotionEngine:
    """
    Evaluates performance of shadow trades and strategies.
    Promotes based on statistical significance (e.g. N > 10, win rate > 55%).
    """

    def __init__(self, db_manager=None):
        self._db_manager = db_manager

    def evaluate_shadow_performance(self, strategy_name: str = "SDK_Shadow") -> Dict[str, Any]:
        """
        Check how well a shadow strategy is doing across different regimes.
        """
        # Note: Shadow trades are stored in the main paper_trades table
        # but their results are also reflected in trade_outcomes if record_outcome was called.
        # However, for shadow-specific promotion, we should look at the paper_trades table
        # or the pipeline_runs if we want to see 'would-be' trades that weren't even logged.

        # Let's look at trade_outcomes but we need a way to distinguish 'shadow' vs 'live' there.
        # Currently record_outcome doesn't store 'is_shadow'.

        # Strategy: For Phase 5, we'll evaluate the accuracy of the 'Agent Ensemble'
        # as a whole within specific regimes. If ensemble accuracy > 60%, we increase
        # the 'Promotion Score'.

        performance = {}
        regimes = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "VOLATILE"]

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            for regime in regimes:
                try:
                    rows = conn.execute(
                        "SELECT outcome FROM trade_outcomes WHERE regime = ?",
                        (regime,),
                    ).fetchall()
                except Exception as e:
                    if "no such table" in str(e).lower():
                        logger.info(
                            "[Promotion] trade_outcomes table not yet created — returning insufficient_data"
                        )
                        return {
                            "status": "insufficient_data",
                            "reason": "trade_outcomes table not yet created",
                        }
                    raise

                if not rows:
                    performance[regime] = {
                        "count": 0,
                        "win_rate": 0.0,
                        "status": "insufficient_data",
                    }
                    continue

                wins = sum(1 for r in rows if r["outcome"] == "WIN")
                total = len(rows)
                win_rate = wins / total

                status = "eligible" if total >= 10 and win_rate > 0.55 else "monitoring"
                if total < 10:
                    status = "insufficient_data"

                performance[regime] = {
                    "count": total,
                    "win_rate": round(win_rate, 3),
                    "status": status,
                }

        return performance

    def generate_promotion_report(self) -> Dict[str, Any]:
        """
        Generates a summary of which regimes/strategies are candidates for promotion.
        """
        perf = self.evaluate_shadow_performance()

        candidates = [reg for reg, stats in perf.items() if stats["status"] == "eligible"]

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "performance_by_regime": perf,
            "promotion_candidates": candidates,
            "recommendation": (
                "Promote to LIVE for: " + ", ".join(candidates)
                if candidates
                else "Maintain shadow mode for all regimes."
            ),
        }

        logger.info(f"[PROMOTION] Report generated. Candidates: {candidates}")
        return report


def get_promotion_engine(db_manager=None):
    return PromotionEngine(db_manager)
