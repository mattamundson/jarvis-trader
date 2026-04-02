"""
Pattern Extractor — US-011
Extracts recurring patterns from completed trades.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A recurring trading pattern discovered in historical trades."""

    name: str
    frequency: int
    win_rate: float
    avg_return: float
    conditions: dict = field(default_factory=dict)
    last_seen: Optional[datetime] = None


class PatternExtractor:
    """
    Analyzes completed trades and extracts recurring patterns.
    Patterns tracked: time-of-day, regime-based, consecutive wins/losses.
    """

    MIN_PATTERN_FREQUENCY = 3

    def __init__(self):
        """Initialize pattern extractor."""
        self.patterns: dict[str, Pattern] = {}
        logger.info("PatternExtractor initialized")

    def extract(self, trades: list[dict]) -> list[Pattern]:
        """
        Extract patterns from completed trades.

        Args:
            trades: List of trade dicts with keys:
                - symbol: str
                - entry_time: datetime or str
                - exit_time: datetime or str
                - pnl: float
                - return_pct: float
                - regime: str
                - won: bool (True if pnl > 0)

        Returns:
            List of discovered Pattern objects.
        """
        if not trades:
            logger.debug("extract() called with empty trades list")
            return []

        try:
            self._extract_time_patterns(trades)
            self._extract_regime_patterns(trades)
            self._extract_streak_patterns(trades)

            result = list(self.patterns.values())
            logger.info(f"Extracted {len(result)} patterns from {len(trades)} trades")
            return result
        except Exception as e:
            logger.exception(f"Error extracting patterns: {e}")
            return []

    def _extract_time_patterns(self, trades: list[dict]) -> None:
        """Extract time-of-day patterns (e.g., morning wins, afternoon losses)."""
        if not trades:
            return

        hour_stats: dict[int, dict] = {}

        for trade in trades:
            try:
                entry_time = self._parse_time(trade.get("entry_time"))
                if not entry_time:
                    continue

                hour = entry_time.hour
                if hour not in hour_stats:
                    hour_stats[hour] = {"wins": 0, "total": 0, "returns": []}

                hour_stats[hour]["total"] += 1
                if trade.get("won"):
                    hour_stats[hour]["wins"] += 1

                ret = float(trade.get("return_pct", 0))
                hour_stats[hour]["returns"].append(ret)
            except Exception as e:
                logger.debug(f"Error processing trade in time pattern: {e}")
                continue

        for hour, stats in hour_stats.items():
            if stats["total"] < self.MIN_PATTERN_FREQUENCY:
                continue

            win_rate = stats["wins"] / stats["total"]
            avg_ret = sum(stats["returns"]) / len(stats["returns"])

            pattern_key = f"time_hour_{hour:02d}"
            pattern = Pattern(
                name=f"Hour {hour:02d}:00 Window",
                frequency=stats["total"],
                win_rate=win_rate,
                avg_return=avg_ret,
                conditions={"hour": hour},
                last_seen=datetime.utcnow(),
            )
            self.patterns[pattern_key] = pattern

    def _extract_regime_patterns(self, trades: list[dict]) -> None:
        """Extract patterns based on market regime."""
        if not trades:
            return

        regime_stats: dict[str, dict] = {}

        for trade in trades:
            regime = trade.get("regime", "unknown")
            if regime not in regime_stats:
                regime_stats[regime] = {"wins": 0, "total": 0, "returns": []}

            regime_stats[regime]["total"] += 1
            if trade.get("won"):
                regime_stats[regime]["wins"] += 1

            ret = float(trade.get("return_pct", 0))
            regime_stats[regime]["returns"].append(ret)

        for regime, stats in regime_stats.items():
            if stats["total"] < self.MIN_PATTERN_FREQUENCY:
                continue

            win_rate = stats["wins"] / stats["total"]
            avg_ret = sum(stats["returns"]) / len(stats["returns"])

            pattern_key = f"regime_{regime}"
            pattern = Pattern(
                name=f"Regime: {regime}",
                frequency=stats["total"],
                win_rate=win_rate,
                avg_return=avg_ret,
                conditions={"regime": regime},
                last_seen=datetime.utcnow(),
            )
            self.patterns[pattern_key] = pattern

    def _extract_streak_patterns(self, trades: list[dict]) -> None:
        """Extract consecutive win/loss streak patterns."""
        if not trades:
            return

        consecutive_wins = 0
        consecutive_losses = 0

        for trade in trades:
            if trade.get("won"):
                consecutive_wins += 1
                consecutive_losses = 0
            else:
                consecutive_losses += 1
                consecutive_wins = 0

            if consecutive_wins >= self.MIN_PATTERN_FREQUENCY:
                pattern_key = f"streak_wins_{consecutive_wins}"
                if pattern_key not in self.patterns:
                    pattern = Pattern(
                        name=f"Win Streak ({consecutive_wins}+)",
                        frequency=1,
                        win_rate=1.0,
                        avg_return=0.0,
                        conditions={"min_consecutive_wins": consecutive_wins},
                        last_seen=datetime.utcnow(),
                    )
                    self.patterns[pattern_key] = pattern
                else:
                    self.patterns[pattern_key].frequency += 1
                    self.patterns[pattern_key].last_seen = datetime.utcnow()

            if consecutive_losses >= self.MIN_PATTERN_FREQUENCY:
                pattern_key = f"streak_losses_{consecutive_losses}"
                if pattern_key not in self.patterns:
                    pattern = Pattern(
                        name=f"Loss Streak ({consecutive_losses}+)",
                        frequency=1,
                        win_rate=0.0,
                        avg_return=0.0,
                        conditions={"min_consecutive_losses": consecutive_losses},
                        last_seen=datetime.utcnow(),
                    )
                    self.patterns[pattern_key] = pattern
                else:
                    self.patterns[pattern_key].frequency += 1
                    self.patterns[pattern_key].last_seen = datetime.utcnow()

    def _parse_time(self, time_val) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if isinstance(time_val, datetime):
            return time_val

        if isinstance(time_val, str):
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
            ]:
                try:
                    return datetime.strptime(time_val, fmt)
                except ValueError:
                    continue

        return None
