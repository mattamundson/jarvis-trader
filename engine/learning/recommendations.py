"""
Learning Recommendations Module — Retrieves relevant patterns for Stage 1 context.

When TechnicalAnalystAgent starts analysis, this module:
1. Queries the pattern library for the given symbol/timeframe
2. Filters by relevance (active patterns, reasonable win rates)
3. Applies exponential temporal decay (half-life = 7 days) — recent patterns weighted 3x older
4. Formats recommendations into human-readable context

Integrates with technical_analyst.py for Stage 1 context injection.
"""

import json
import logging
import math
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class Recommendation:
    """A single recommendation derived from historical patterns."""

    def __init__(
        self,
        pattern_type: str,
        conditions: dict,
        win_rate: float,
        sample_count: int,
        last_seen: str,
    ):
        self.pattern_type = pattern_type
        self.conditions = conditions
        self.win_rate = win_rate
        self.sample_count = sample_count
        self.last_seen = last_seen

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "conditions": self.conditions,
            "win_rate": self.win_rate,
            "sample_count": self.sample_count,
            "last_seen": self.last_seen,
        }

    def to_text(self) -> str:
        """Format recommendation as human-readable text for prompt injection."""
        win_pct = round(self.win_rate * 100, 1)
        return (
            f"Pattern: {self.pattern_type} ({win_pct}% win rate over {self.sample_count} trades) "
            f"conditions: {json.dumps(self.conditions)}"
        )


_DECAY_HALF_LIFE_DAYS = 7.0
_WIN_RATE_HIGH_THRESHOLD = 0.55  # inject if win_rate > 55%
_WIN_RATE_LOW_THRESHOLD = 0.40   # inject if win_rate < 40% (bearish edge)


def _decay_weight(last_seen_iso: str) -> float:
    """
    Exponential temporal decay weight based on pattern age.

    Formula: weight = exp(-0.693 * age_days / half_life)
    At age=0: weight=1.0 | At age=7d: weight=0.5 | At age=14d: weight=0.25

    Args:
        last_seen_iso: ISO datetime string of when the pattern was last observed

    Returns:
        Float in (0, 1] — recent patterns score near 1.0, old patterns near 0.0
    """
    try:
        last_seen = datetime.fromisoformat(last_seen_iso)
        age_days = (datetime.now() - last_seen).total_seconds() / 86400.0
        age_days = max(0.0, age_days)
        return math.exp(-0.693 * age_days / _DECAY_HALF_LIFE_DAYS)
    except Exception:
        return 0.5  # neutral weight if parse fails


async def get_recommendations(
    symbol: str,
    timeframe: str = "1h",
    db_manager=None,
) -> list[str]:
    """
    Retrieve relevant pattern recommendations for a symbol/timeframe.

    Args:
        symbol: Trading symbol (e.g., MCL, MNQ)
        timeframe: Timeframe (e.g., 1h, 1d) - informational, not filtered on
        db_manager: Optional database manager for pattern lookup

    Returns:
        List of formatted recommendation strings (empty list if no patterns or DB unavailable)

    Note:
        This function is designed to be called from technical_analyst.py before
        LLM synthesis, and to gracefully return empty list on any errors.
        Pattern injection in Stage 1 must not block pipeline if this fails.
    """
    try:
        if not db_manager:
            logger.debug(f"[LEARNING] Recommendations skipped for {symbol}: no database manager")
            return []

        symbol = symbol.upper()

        # Query active patterns for this symbol (last 14 days)
        cutoff = (datetime.now() - timedelta(days=14)).isoformat()
        try:
            rows = await db_manager.fetch_all(
                "SELECT pattern_type, conditions, win_rate, sample_count, last_seen "
                "FROM trading_patterns "
                "WHERE symbol = ? AND is_active = 1 AND last_seen >= ? "
                "ORDER BY win_rate DESC, sample_count DESC "
                "LIMIT 5",
                (symbol, cutoff),
            )
        except Exception as query_err:
            logger.debug(f"[LEARNING] Pattern query failed for {symbol}: {query_err}")
            return []

        if not rows:
            logger.debug(f"[LEARNING] No active patterns found for {symbol}")
            return []

        weighted_recs: list[tuple[float, str]] = []
        for row in rows:
            try:
                # Parse conditions JSON if stored as string
                conditions = row.get("conditions", {})
                if isinstance(conditions, str):
                    conditions = json.loads(conditions)

                win_rate = float(row.get("win_rate", 0.0))
                sample_count = int(row.get("sample_count", 0))
                last_seen = row.get("last_seen", "")

                # Win-rate guard: only inject patterns with a clear edge.
                # Skip 50/50 noise (win_rate between 40% and 55%).
                has_edge = win_rate > _WIN_RATE_HIGH_THRESHOLD or win_rate < _WIN_RATE_LOW_THRESHOLD
                if sample_count < 2 or not has_edge:
                    continue

                # Temporal decay: weight recent patterns up to 3x older ones.
                # exp decay with half-life=7d means 1d-old pattern scores ~0.91,
                # 7d-old scores 0.5, 14d-old scores 0.25.
                weight = _decay_weight(last_seen)

                # Effective win_rate biased toward recent patterns
                effective_win_rate = win_rate * weight

                rec = Recommendation(
                    pattern_type=row.get("pattern_type", "unknown"),
                    conditions=conditions,
                    win_rate=effective_win_rate,
                    sample_count=sample_count,
                    last_seen=last_seen,
                )
                weighted_recs.append((weight, rec.to_text()))
            except Exception as rec_err:
                logger.debug(f"[LEARNING] Recommendation parse failed: {rec_err}")
                continue

        # Sort by decay weight descending — most recent patterns appear first
        weighted_recs.sort(key=lambda x: x[0], reverse=True)
        recommendations = [text for _, text in weighted_recs]

        if recommendations:
            logger.info(f"[LEARNING] {len(recommendations)} recommendations injected for {symbol}")

        return recommendations

    except Exception as e:
        logger.error(f"[LEARNING] get_recommendations failed for {symbol}: {e}")
        return []


def format_recommendations_for_prompt(recommendations: list[str]) -> str:
    """
    Format a list of recommendations into a prompt injection string.

    Args:
        recommendations: List of formatted recommendation strings

    Returns:
        Human-readable context block ready for prompt injection
    """
    if not recommendations:
        return ""

    context = "## Historical Pattern Context (from learning system):\n"
    for i, rec in enumerate(recommendations, 1):
        context += f"{i}. {rec}\n"

    context += "\nConsider these patterns when forming your analysis.\n"
    return context
