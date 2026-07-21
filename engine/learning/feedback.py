"""
Trading Feedback Module — Generates lessons from closed trades.

When a trade closes, this module:
1. Analyzes the trade outcome
2. Generates a lesson (win/loss pattern, execution quality)
3. Persists the lesson for pattern aggregation

Used by portfolio/tracker.py:close_trade() via async callbacks.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Pattern-library bridge (roadmap 1.7). A closed-trade lesson now flows into
# patterns.update_patterns_from_feedback so the trading_patterns table actually
# gets populated — previously the generated feedback was returned and dropped by
# the caller, and the module docstring's "persists the lesson for pattern
# aggregation" was aspirational. Dual-import for the engine's two import roots;
# None-guarded so a missing module can never break feedback generation.
try:
    from learning.patterns import update_patterns_from_feedback
except ImportError:  # pragma: no cover - import-path resilience
    try:
        from engine.learning.patterns import update_patterns_from_feedback
    except ImportError:
        update_patterns_from_feedback = None


class TradeOutcomeFeedback:
    """Represents feedback generated from a single trade closure."""

    def __init__(
        self,
        trade_id: str,
        symbol: str,
        pnl: float,
        entry_price: float,
        exit_price: float,
        entry_time: str,
        exit_time: str,
        action: str,
    ):
        self.trade_id = trade_id
        self.symbol = symbol
        self.pnl = pnl
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.action = action
        self.generated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "pnl": self.pnl,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "action": self.action,
            "generated_at": self.generated_at,
        }


async def process_trade_outcome(
    trade_id: str,
    symbol: str,
    pnl: float,
    entry_price: float,
    exit_price: float,
    entry_time: str,
    exit_time: str,
    action: str,
    db_manager=None,
) -> TradeOutcomeFeedback:
    """
    Process a closed trade and generate feedback/lesson.

    Args:
        trade_id: Unique trade identifier
        symbol: Trading symbol (e.g., MCL, MNQ)
        pnl: Realized P&L in USD
        entry_price: Entry price
        exit_price: Exit price
        entry_time: Entry timestamp (ISO format)
        exit_time: Exit timestamp (ISO format)
        action: Trade action (long/short/buy/sell)
        db_manager: Optional DB manager; when supplied, the outcome is also fed
            to patterns.update_patterns_from_feedback to upsert trading_patterns.

    Returns:
        TradeOutcomeFeedback object with lesson

    Note:
        This function is non-blocking and safe to call from sync code via
        asyncio.create_task() in portfolio/tracker.py
    """
    try:
        # Create feedback object
        feedback = TradeOutcomeFeedback(
            trade_id=trade_id,
            symbol=symbol,
            pnl=pnl,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time,
            action=action,
        )

        # Generate lesson text based on outcome
        if pnl > 0:
            lesson_type = "winning_trade"
            r_multiple = pnl / 10.0 if pnl > 0 else 0.0  # simple R estimation
            lesson_text = f"Winning trade on {symbol}: +${pnl:.2f} ({r_multiple:.1f}R). "
            lesson_text += (
                f"Action: {action.upper()}, duration: {_get_trade_duration(entry_time, exit_time)}"
            )
        elif pnl < 0:
            lesson_type = "losing_trade"
            lesson_text = f"Losing trade on {symbol}: -${abs(pnl):.2f}. "
            lesson_text += (
                f"Action: {action.upper()}, duration: {_get_trade_duration(entry_time, exit_time)}"
            )
        else:
            lesson_type = "breakeven_trade"
            lesson_text = f"Breakeven trade on {symbol}. Action: {action.upper()}"

        logger.info(f"[LEARNING] Feedback generated for trade {trade_id[:8]}: {lesson_type}")

        # Store feedback metadata for pattern extraction
        feedback.lesson_type = lesson_type
        feedback.lesson_text = lesson_text

        # Feed the pattern library (roadmap 1.7). Closes the review->improve
        # dead-end: the generated lesson used to be returned and dropped. Now the
        # outcome also upserts the trading_patterns table (when a db_manager is
        # supplied). Fail-open — a pattern-update error must never break
        # trade-close feedback.
        if update_patterns_from_feedback is not None:
            try:
                await update_patterns_from_feedback(
                    {
                        "symbol": symbol,
                        "pnl": pnl,
                        "entry_time": entry_time,
                        "exit_time": exit_time,
                        "action": action,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                    },
                    db_manager=db_manager,
                )
            except Exception as _pat_exc:
                logger.debug(
                    f"[LEARNING] Pattern update skipped for {trade_id[:8]}: {_pat_exc}"
                )

        return feedback

    except Exception as e:
        logger.error(f"[LEARNING] Failed to process trade outcome for {trade_id}: {e}")
        raise


def _get_trade_duration(entry_time_str: str, exit_time_str: str) -> str:
    """Compute human-readable trade duration."""
    try:
        for _fmt in ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]:
            try:
                entry = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                exit_dt = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                delta = exit_dt - entry
                hours = delta.total_seconds() / 3600
                if hours < 1:
                    return f"{int(delta.total_seconds() / 60)} min"
                elif hours < 24:
                    return f"{hours:.1f} h"
                else:
                    return f"{hours / 24:.1f} days"
            except (ValueError, AttributeError):
                continue
        return "unknown duration"
    except Exception:
        return "unknown duration"
