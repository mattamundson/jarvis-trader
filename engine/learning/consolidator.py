"""
Trading Memory Consolidator — adapted from Claude Code's /dream command.
Nightly consolidation of trading patterns into actionable pattern database.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from engine.learning.promotion import get_promotion_engine
except ImportError:
    get_promotion_engine = None


class TradingMemoryConsolidator:
    """
    Converts raw trade history into pattern database.
    Runs nightly, triggered by eod_scheduler.
    """

    def __init__(self, db_manager=None, llm_client=None):
        self._db = db_manager
        self._client = llm_client
        self._promotion_engine = get_promotion_engine(db_manager) if get_promotion_engine else None

    async def consolidate_daily(self, target_date: str = None) -> dict:
        """
        Run nightly consolidation:
        1. Fetch all trades from target_date
        2. Extract patterns (winning conditions, losing conditions)
        3. Score signal accuracy (which directions were correct)
        4. Optional: LLM insights via Haiku
        5. Persist patterns to trading_patterns table
        6. Prune stale patterns (not seen in 30+ days)
        """
        target_date = target_date or date.today().isoformat()
        logger.info(f"Memory consolidation starting for {target_date}")

        # Fetch trades for the day
        trades = self._fetch_trades(target_date)
        if not trades:
            return {"date": target_date, "status": "no_trades", "patterns": [], "accuracy": {}}

        # Extract patterns
        patterns = self._extract_patterns(trades)

        # Score signal accuracy
        accuracy = self._score_signal_accuracy(trades)

        # Persist patterns
        if self._db:
            for pattern in patterns:
                await self._upsert_pattern(pattern, target_date)
            await self._prune_stale_patterns()

        # Optional LLM insights
        insights = None
        if self._client and len(trades) > 0:
            insights = await self._generate_insights(trades, patterns, accuracy)

        # Promotion check
        promotion_report = None
        if self._promotion_engine:
            promotion_report = self._promotion_engine.generate_promotion_report()

        result = {
            "date": target_date,
            "status": "complete",
            "trades_analyzed": len(trades),
            "patterns_extracted": len(patterns),
            "accuracy": accuracy,
            "insights": insights,
            "promotion_report": promotion_report,
        }
        logger.info(f"Memory consolidation complete: {len(patterns)} patterns, accuracy={accuracy}")
        return result

    async def get_active_patterns(self) -> list[dict]:
        """Return patterns active in the last 14 days."""
        if not self._db:
            return []
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        try:
            rows = self._db.fetch_all(
                "SELECT * FROM trading_patterns WHERE is_active=1 AND last_seen >= ? ORDER BY win_rate DESC LIMIT 20",
                (cutoff,),
            )
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.error(f"get_active_patterns error: {e}")
            return []

    async def get_signal_accuracy(self, days: int = 30) -> dict:
        """Track signal accuracy over N days."""
        if not self._db:
            return {"days": days, "total": 0, "correct": 0, "accuracy_pct": 0}
        try:
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            # paper_trades uses 'side' (buy/sell), not 'direction'
            rows = self._db.fetch_all(
                "SELECT side, COUNT(*) as total, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins "
                "FROM paper_trades WHERE entry_time >= ? GROUP BY side",
                (cutoff,),
            )
            result = {"days": days, "by_direction": {}, "total": 0, "correct": 0}
            for row in rows or []:
                d = dict(row)
                side = d.get("side", "unknown")
                # Map side to direction for reporting consistency
                direction = "long" if "buy" in side.lower() or "long" in side.lower() else "short"
                result["by_direction"][direction] = {
                    "total": d.get("total", 0),
                    "wins": d.get("wins", 0),
                    "accuracy_pct": round(d.get("wins", 0) / max(d.get("total", 1), 1) * 100, 1),
                }
                result["total"] += d.get("total", 0)
                result["correct"] += d.get("wins", 0)
            if result["total"] > 0:
                result["accuracy_pct"] = round(result["correct"] / result["total"] * 100, 1)
            return result
        except Exception as e:
            logger.error(f"get_signal_accuracy error: {e}")
            return {"days": days, "total": 0, "correct": 0, "accuracy_pct": 0}

    def _extract_patterns(self, trades: list[dict]) -> list[dict]:
        """Simple rule-based pattern extraction from trades."""
        patterns = []

        # Pattern 1: Time-of-day performance
        hour_pnl = {}
        for trade in trades:
            try:
                hour = datetime.fromisoformat(trade.get("entry_time", "")).hour
                hour_pnl.setdefault(hour, []).append(trade.get("pnl", 0))
            except Exception:
                continue

        for hour, pnls in hour_pnl.items():
            if len(pnls) >= 2:
                wins = sum(1 for p in pnls if p > 0)
                win_rate = wins / len(pnls)
                avg_return = sum(pnls) / len(pnls)
                if win_rate > 0.6 or win_rate < 0.3:
                    patterns.append(
                        {
                            "pattern_type": f"hour_{hour:02d}_performance",
                            "symbol": "GLOBAL",
                            "category": "time",
                            "conditions": json.dumps({"hour": hour}),
                            "win_count": wins,
                            "loss_count": len(pnls) - wins,
                            "win_rate": round(win_rate, 3),
                            "avg_return": round(avg_return, 2),
                            "frequency": len(pnls),
                        }
                    )

        # Pattern 2: Direction bias
        long_trades = [t for t in trades if t.get("side", "").lower() in ("long", "buy")]
        short_trades = [t for t in trades if t.get("side", "").lower() in ("short", "sell")]

        for direction, direction_trades in [("long", long_trades), ("short", short_trades)]:
            if len(direction_trades) >= 2:
                pnls = [t.get("pnl", 0) for t in direction_trades]
                wins = sum(1 for p in pnls if p > 0)
                win_rate = wins / len(pnls)
                patterns.append(
                    {
                        "pattern_type": f"direction_{direction}",
                        "symbol": direction_trades[0].get("symbol", "GLOBAL"),
                        "category": "regime",
                        "conditions": json.dumps(
                            {"direction": direction, "date": date.today().isoformat()}
                        ),
                        "win_count": wins,
                        "loss_count": len(pnls) - wins,
                        "win_rate": round(win_rate, 3),
                        "avg_return": round(sum(pnls) / len(pnls), 2),
                        "frequency": len(pnls),
                    }
                )

        return patterns

    def _score_signal_accuracy(self, trades: list[dict]) -> dict:
        """Score how accurate the pipeline signals were today."""
        if not trades:
            return {"total": 0, "wins": 0, "accuracy_pct": 0}
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total = len(trades)
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "accuracy_pct": round(wins / total * 100, 1),
            "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        }

    def _fetch_trades(self, target_date: str) -> list[dict]:
        """Fetch paper trades for the given date from DB."""
        if not self._db:
            return []
        try:
            # paper_trades uses DATE(entry_time) or similar
            rows = self._db.fetch_all(
                "SELECT * FROM paper_trades WHERE DATE(entry_time) = ? ORDER BY entry_time",
                (target_date,),
            )
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.debug(f"fetch_trades: {e}")
            return []

    async def _upsert_pattern(self, pattern: dict, today: str) -> None:
        """Insert or update a pattern in the DB."""
        if not self._db:
            return
        try:
            # Use pattern_hash for uniqueness per symbol
            import hashlib
            key = f"{pattern.get('symbol', 'GLOBAL')}:{pattern['pattern_type']}"
            pattern_hash = hashlib.md5(key.encode()).hexdigest()[:16]

            existing = self._db.fetch_one(
                "SELECT id, win_count, loss_count FROM trading_patterns WHERE pattern_hash = ?",
                (pattern_hash,),
            )
            if existing:
                new_win = existing["win_count"] + pattern["win_count"]
                new_loss = existing["loss_count"] + pattern["loss_count"]
                new_win_rate = round(new_win / (new_win + new_loss), 3) if (new_win + new_loss) > 0 else 0.0

                self._db.execute(
                    "UPDATE trading_patterns SET win_count=?, loss_count=?, win_rate=?, avg_return=?, "
                    "sample_count=win_count+loss_count, last_seen=?, is_active=1 WHERE pattern_hash=?",
                    (
                        new_win,
                        new_loss,
                        new_win_rate,
                        pattern["avg_return"],
                        today,
                        pattern_hash,
                    ),
                )
            else:
                self._db.execute(
                    "INSERT INTO trading_patterns "
                    "(pattern_hash, symbol, pattern_type, conditions, win_count, loss_count, "
                    "win_rate, avg_return, sample_count, last_seen, created_at, is_active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        pattern_hash,
                        pattern.get("symbol", "GLOBAL"),
                        pattern["pattern_type"],
                        pattern["conditions"],
                        pattern["win_count"],
                        pattern["loss_count"],
                        pattern["win_rate"],
                        pattern["avg_return"],
                        pattern["win_count"] + pattern["loss_count"],
                        today,
                        datetime.now().isoformat(),
                    ),
                )
        except Exception as e:
            logger.error(f"upsert_pattern error: {e}")

    async def _prune_stale_patterns(self) -> None:
        """Mark patterns not seen in 30 days as inactive."""
        if not self._db:
            return
        try:
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            self._db.execute(
                "UPDATE trading_patterns SET is_active=0 WHERE last_seen < ?", (cutoff,)
            )
        except Exception as e:
            logger.error(f"prune_stale_patterns error: {e}")

    async def _generate_insights(self, trades, patterns, accuracy) -> Optional[str]:
        """Generate LLM insights using Haiku."""
        try:
            summary = f"""Trades today: {len(trades)}
Accuracy: {accuracy.get('accuracy_pct', 0)}%
Total P&L: {accuracy.get('total_pnl', 0)}
Patterns found: {len(patterns)}
Key patterns: {[p['name'] for p in patterns[:5]]}"""

            result = await self._client.call(
                model="claude-haiku-4-5-20251001",
                system="You are a trading coach analyzing daily performance patterns.",
                messages=[
                    {
                        "role": "user",
                        "content": f"Provide 3 actionable insights from today's trading:\n{summary}",
                    }
                ],
                max_tokens=300,
            )
            return result.get("content", [{}])[0].get("text", "")
        except Exception as e:
            logger.error(f"LLM insights failed: {e}")
            return None
