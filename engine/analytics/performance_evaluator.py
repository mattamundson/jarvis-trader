#!/usr/bin/env python3
"""
JARVIS TRADER -- performance_evaluator.py
=========================================
Task 4 of the Top-5 ROI Priority List: The Learn Loop.
Reads the most recent QuantStats output or SQLite PnL history and classifies
the trailing regime (toxic / confirmed / neutral) for the TPO strategy.

NOTE (D3-06): this script does NOT modulate risk automatically. It only logs
the regime read (see the docstring on `evaluate_daily_performance` for the
history and why real modulation is out of scope pending D1-03). Any actual
change to MAX_CONTRACTS_PER_INSTRUMENT is a manual, Amo-gated action.
"""

import logging
import sys

try:
    from config import settings  # noqa: F401  (presence-check only)
    from database.db_manager import DatabaseManager
except ImportError as e:
    print(f"Must run from engine root: {e}")
    sys.exit(1)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def evaluate_daily_performance(db: DatabaseManager):
    """
    Evaluates trailing 5-day performance and reports whether the algorithmic
    edge looks toxic, confirmed, or neutral.

    NOTE (D3-06, 2026-07-26): this function used to call a `_modulate_env_risk`
    helper on the two branches below. That helper never wrote to .env, never
    wrote to the database, and had no return value anything downstream
    consumed -- it only logged an INFO line reporting a fake success, which
    made a dead control indistinguishable from a working one in the
    operational record. It has been removed rather than "fixed" because
    implementing real dynamic risk modulation (actually rewriting
    MAX_CONTRACTS_PER_INSTRUMENT, or wiring a DB-backed setting into the live
    config) is a new safety control that needs its own Amo sign-off and is
    blocked on D1-03 (unresolved: what the real MAX_CONTRACTS ceiling should
    even be). Every real enforcement site reads
    `settings.MAX_CONTRACTS_PER_INSTRUMENT` straight from the environment
    (safety_layer.py, trader.py, portfolio_router.py, safety_router.py) and
    was never touched by the removed call. This function now only reports the
    regime read; it takes no risk-limiting action.
    """
    logger.info("Initializing Performance Evaluator Cron...")

    snapshots = db.get_recent_summary(limit=5)

    if not snapshots or len(snapshots) < 3:
        logger.info("Insufficient trailing data (<3 days). Holding base risk limits steady.")
        return

    # Calculate trailing win rate based on daily PnL positivity
    winning_days = sum(1 for snap in snapshots if snap.get("daily_pnl", 0) > 0)
    win_rate = winning_days / len(snapshots)

    total_trailing_pnl = sum(snap.get("daily_pnl", 0) for snap in snapshots)

    logger.info(f"Trailing 5-Day Alpha metrics -> Win Rate: {win_rate*100:.1f}% | Net PnL: ${total_trailing_pnl:.2f}")

    # Regime classification only. No automatic risk-limit change is applied --
    # see the D3-06 note in the docstring above for why.
    if win_rate < 0.40 and total_trailing_pnl < 0:
        logger.warning(
            "ALGORITHMIC ROT DETECTED (win_rate=%.1f%%, trailing_pnl=$%.2f) -- "
            "NO automatic risk modulation is applied; MAX_CONTRACTS_PER_INSTRUMENT "
            "is unchanged. Manual review required.",
            win_rate * 100,
            total_trailing_pnl,
        )
    elif win_rate >= 0.60 and total_trailing_pnl > 0:
        logger.info("EDGE CONFIRMED: Market regime aligns with bounds. Holding steady.")
    else:
        logger.info("MARKET REGIME NEUTRAL. Awaiting further data.")


def main():
    print("=========================================")
    print("JARVIS TRADER :: PERFORMANCE EVALUATOR")
    print("=========================================")
    try:
        db = DatabaseManager()
        evaluate_daily_performance(db)
    except Exception as e:
        logger.error(f"Evaluator failed: {e}")

if __name__ == "__main__":
    main()
