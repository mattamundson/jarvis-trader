"""
Trading Patterns Module — Aggregates lessons into recurring patterns.

When feedback is generated from a closed trade, this module:
1. Analyzes the trade outcome (win/loss, symbol, regime)
2. Updates pattern library with win rates and frequencies
3. Identifies recurring conditions for pattern recommendations

Integrates with consolidator.py for persistent storage.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TradePattern:
    """Represents a recurring trading pattern discovered from closed trades."""

    def __init__(
        self,
        symbol: str,
        pattern_type: str,
        conditions: dict,
        win_count: int = 0,
        loss_count: int = 0,
        last_seen: Optional[str] = None,
    ):
        self.symbol = symbol
        self.pattern_type = pattern_type  # "symbol_win", "symbol_loss", "time_window", etc.
        self.conditions = conditions  # e.g., {"symbol": "MCL", "hour": 10}
        self.win_count = win_count
        self.loss_count = loss_count
        self.last_seen = last_seen or datetime.now().isoformat()
        self.sample_count = win_count + loss_count
        self.win_rate = (
            round(win_count / self.sample_count, 3) if self.sample_count > 0 else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "pattern_type": self.pattern_type,
            "conditions": self.conditions,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "sample_count": self.sample_count,
            "win_rate": self.win_rate,
            "last_seen": self.last_seen,
        }


async def update_patterns_from_feedback(
    feedback_outcome: dict,
    db_manager=None,
) -> Optional[list]:
    """
    Update pattern library based on a single trade outcome from feedback.

    Args:
        feedback_outcome: Dict with trade_id, symbol, pnl, entry_time, etc.
        db_manager: Optional database manager for persistence

    Returns:
        List of TradePattern objects created/updated, or None on error

    Note:
        This function is async to support non-blocking updates from portfolio/tracker.py
        Integration point: Called by learning system after feedback.process_trade_outcome()
    """
    try:
        symbol = feedback_outcome.get("symbol", "").upper()
        pnl = feedback_outcome.get("pnl", 0.0)
        entry_time_str = feedback_outcome.get("entry_time", "")
        is_winner = pnl > 0

        if not symbol:
            logger.warning("[LEARNING] Pattern update skipped: no symbol in feedback")
            return None

        patterns = []

        # Pattern 1: Simple win/loss by symbol
        pattern_type = f"{symbol}_winner" if is_winner else f"{symbol}_loser"
        pattern = TradePattern(
            symbol=symbol,
            pattern_type=pattern_type,
            conditions={"symbol": symbol, "outcome": "win" if is_winner else "loss"},
            win_count=1 if is_winner else 0,
            loss_count=0 if is_winner else 1,
        )
        patterns.append(pattern)

        # Pattern 2: Time-of-day performance (if we can extract hour)
        try:
            from datetime import datetime

            for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    entry_dt = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                    hour = entry_dt.hour
                    time_pattern = TradePattern(
                        symbol=symbol,
                        pattern_type=f"time_window_{hour:02d}",
                        conditions={"symbol": symbol, "entry_hour": hour},
                        win_count=1 if is_winner else 0,
                        loss_count=0 if is_winner else 1,
                    )
                    patterns.append(time_pattern)
                    break
                except (ValueError, AttributeError):
                    continue
        except Exception as e:
            logger.debug(f"[LEARNING] Time pattern extraction failed: {e}")

        # Pattern 3: Persist to DB if available
        if db_manager:
            try:
                for pattern in patterns:
                    # Try to upsert pattern into trading_patterns table
                    await _upsert_pattern_to_db(db_manager, pattern)
            except Exception as db_err:
                logger.warning(f"[LEARNING] Failed to persist patterns to DB: {db_err}")

        logger.info(
            f"[LEARNING] Patterns updated for {symbol}: "
            f"{len(patterns)} patterns extracted, "
            f"pnl={pnl:+.2f}, outcome={'win' if is_winner else 'loss'}"
        )
        return patterns

    except Exception as e:
        logger.error(f"[LEARNING] Pattern update failed: {e}")
        return None


async def _upsert_pattern_to_db(db_manager, pattern: TradePattern) -> None:
    """Upsert a pattern into the trading_patterns table."""
    try:
        pattern_hash = _compute_pattern_hash(pattern.symbol, pattern.pattern_type)

        # Check if pattern exists
        existing = await db_manager.fetch_one(
            "SELECT id, win_count, loss_count FROM trading_patterns WHERE pattern_hash = ?",
            (pattern_hash,),
        )

        if existing:
            # Update win/loss counts
            new_win = existing["win_count"] + pattern.win_count
            new_loss = existing["loss_count"] + pattern.loss_count
            new_win_rate = round(new_win / (new_win + new_loss), 3) if (new_win + new_loss) > 0 else 0.0

            await db_manager.execute(
                "UPDATE trading_patterns SET win_count=?, loss_count=?, win_rate=?, "
                "last_seen=?, is_active=1 WHERE pattern_hash=?",
                (
                    new_win,
                    new_loss,
                    new_win_rate,
                    datetime.now().isoformat(),
                    pattern_hash,
                ),
            )
        else:
            # Insert new pattern
            await db_manager.execute(
                "INSERT INTO trading_patterns "
                "(pattern_hash, symbol, pattern_type, conditions, win_count, loss_count, "
                "win_rate, is_active, last_seen, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    pattern_hash,
                    pattern.symbol,
                    pattern.pattern_type,
                    json.dumps(pattern.conditions),
                    pattern.win_count,
                    pattern.loss_count,
                    pattern.win_rate,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
    except Exception as e:
        logger.error(f"[LEARNING] DB upsert failed for pattern: {e}")
        raise


def _compute_pattern_hash(symbol: str, pattern_type: str) -> str:
    """Compute a deterministic hash for pattern deduplication."""
    import hashlib

    key = f"{symbol}:{pattern_type}"
    return hashlib.md5(key.encode()).hexdigest()[:16]
