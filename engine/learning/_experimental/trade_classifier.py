"""
Trade Classifier — US-012
Classifies completed trades by outcome quality (A/B/C/D/F).
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Grading thresholds
R_MULTIPLE_EXCELLENT = 3.0
R_MULTIPLE_GOOD = 2.0
R_MULTIPLE_OK = 1.0
R_MULTIPLE_POOR = 0.0

TIME_EFFICIENCY_QUICK = 1.5
TIME_EFFICIENCY_NORMAL = 3.0
TIME_EFFICIENCY_SLOW = 6.0

SLIPPAGE_EXCELLENT = 0.01
SLIPPAGE_GOOD = 0.05
SLIPPAGE_OK = 0.10


@dataclass
class TradeClassification:
    """Classification of a single trade."""

    trade_id: str
    grade: str
    setup_quality: float
    execution_quality: float
    factors: list[str] = field(default_factory=list)


class TradeClassifier:
    """
    Classifies completed trades by outcome quality.
    Grades: A (excellent), B (good), C (ok), D (poor), F (terrible)
    """

    def __init__(self):
        """Initialize classifier."""
        logger.info("TradeClassifier initialized")

    def classify(self, trade: dict) -> TradeClassification:
        """
        Classify a single trade.

        Args:
            trade: Dict with keys:
                - id: str (trade ID)
                - pnl: float (realized P&L)
                - risk: float (risk taken in dollars)
                - entry_price: float
                - exit_price: float
                - time_in_trade: float (hours)
                - target_atr: float (ATR * target_multiplier)
                - regime: str
                - regime_aligned: bool
                - slippage: float (dollars)

        Returns:
            TradeClassification with grade and factors.
        """
        try:
            trade_id = trade.get("id", "unknown")
            setup_quality = self._calc_setup_quality(trade)
            execution_quality = self._calc_execution_quality(trade)

            r_multiple = self._calc_r_multiple(trade)
            time_efficiency = self._calc_time_efficiency(trade)
            regime_aligned = trade.get("regime_aligned", False)
            slippage_pct = self._calc_slippage_pct(trade)

            grade, factors = self._determine_grade(
                r_multiple, time_efficiency, regime_aligned, slippage_pct
            )

            return TradeClassification(
                trade_id=trade_id,
                grade=grade,
                setup_quality=setup_quality,
                execution_quality=execution_quality,
                factors=factors,
            )
        except Exception as e:
            logger.exception(f"Error classifying trade {trade.get('id')}: {e}")
            return TradeClassification(
                trade_id=trade.get("id", "unknown"),
                grade="F",
                setup_quality=0.0,
                execution_quality=0.0,
                factors=["classification_error"],
            )

    def _calc_setup_quality(self, trade: dict) -> float:
        """
        Setup quality: regime alignment, trend confirmation, entry signal quality.
        Returns 0.0–1.0.
        """
        score = 0.0

        if trade.get("regime_aligned"):
            score += 0.3

        entry_confidence = trade.get("entry_confidence", 0.5)
        if entry_confidence > 0.8:
            score += 0.3
        elif entry_confidence > 0.6:
            score += 0.15

        if trade.get("won"):
            score += 0.2
        elif trade.get("pnl", 0) < -abs(trade.get("risk", 0)):
            score -= 0.1

        return min(1.0, max(0.0, score))

    def _calc_execution_quality(self, trade: dict) -> float:
        """
        Execution quality: slippage, time efficiency, stop loss respect.
        Returns 0.0–1.0.
        """
        score = 0.5

        slippage_pct = self._calc_slippage_pct(trade)
        if slippage_pct < 0.01:
            score += 0.2
        elif slippage_pct > 0.10:
            score -= 0.2

        time_eff = self._calc_time_efficiency(trade)
        if time_eff < 1.0:
            score += 0.15
        elif time_eff > 6.0:
            score -= 0.1

        return min(1.0, max(0.0, score))

    def _calc_r_multiple(self, trade: dict) -> float:
        """Calculate R-multiple: profit / risk taken."""
        risk = float(trade.get("risk", 1.0))
        if risk <= 0:
            return 0.0

        pnl = float(trade.get("pnl", 0))
        return pnl / risk

    def _calc_time_efficiency(self, trade: dict) -> float:
        """
        Time to profit ratio.
        Quick wins (< 1.5h) score higher than slow trades.
        """
        time_hours = float(trade.get("time_in_trade", 3.0))
        if time_hours <= 0:
            return 0.0

        return time_hours

    def _calc_slippage_pct(self, trade: dict) -> float:
        """Calculate slippage as percentage of entry price."""
        entry = float(trade.get("entry_price", 1.0))
        if entry <= 0:
            return 0.0

        slippage_dollars = float(trade.get("slippage", 0))
        return abs(slippage_dollars) / entry

    def _determine_grade(
        self, r_multiple: float, time_eff: float, regime_aligned: bool, slippage_pct: float
    ) -> tuple[str, list[str]]:
        """
        Determine letter grade and factors.

        Grading logic:
        - A: R >= 3.0, fast, aligned
        - B: R >= 2.0, normal time, good slippage
        - C: R >= 1.0, ok metrics
        - D: R >= 0.0, slow/misaligned
        - F: R < 0.0
        """
        if r_multiple < 0:
            return "F", ["loss", "negative_r_multiple"]

        if r_multiple >= R_MULTIPLE_EXCELLENT:
            return self._grade_excellent(r_multiple, time_eff, regime_aligned, slippage_pct)

        if r_multiple >= R_MULTIPLE_GOOD:
            return self._grade_good(r_multiple, time_eff, regime_aligned, slippage_pct)

        if r_multiple >= R_MULTIPLE_OK:
            return self._grade_ok(r_multiple, time_eff, regime_aligned, slippage_pct)

        return self._grade_poor(r_multiple, time_eff, regime_aligned, slippage_pct)

    def _grade_excellent(
        self, r_multiple: float, time_eff: float, regime_aligned: bool, slippage_pct: float
    ) -> tuple[str, list[str]]:
        """Grade A-range (excellent R-multiple)."""
        factors = [f"excellent_r_multiple_{r_multiple:.2f}"]
        if time_eff < TIME_EFFICIENCY_QUICK:
            factors.append("quick_execution")
            if regime_aligned:
                return "A", factors + ["regime_aligned"]
            return "A", factors
        if regime_aligned and slippage_pct < SLIPPAGE_GOOD:
            return "A", factors + ["regime_aligned", "low_slippage"]
        return "B", factors

    def _grade_good(
        self, r_multiple: float, time_eff: float, regime_aligned: bool, slippage_pct: float
    ) -> tuple[str, list[str]]:
        """Grade B-range (good R-multiple)."""
        factors = [f"good_r_multiple_{r_multiple:.2f}"]
        if time_eff < TIME_EFFICIENCY_NORMAL and slippage_pct < SLIPPAGE_OK:
            return "B", factors + ["good_execution"]
        if regime_aligned:
            return "B", factors + ["regime_aligned"]
        return "C", factors

    def _grade_ok(
        self, r_multiple: float, time_eff: float, regime_aligned: bool, slippage_pct: float
    ) -> tuple[str, list[str]]:
        """Grade C-range (ok R-multiple)."""
        factors = [f"ok_r_multiple_{r_multiple:.2f}"]
        if regime_aligned and time_eff < TIME_EFFICIENCY_SLOW:
            return "C", factors + ["regime_aligned"]
        if slippage_pct < SLIPPAGE_EXCELLENT:
            return "C", factors + ["low_slippage"]
        return "D", factors

    def _grade_poor(
        self, r_multiple: float, time_eff: float, regime_aligned: bool, slippage_pct: float
    ) -> tuple[str, list[str]]:
        """Grade D-range (poor R-multiple)."""
        factors = [f"poor_r_multiple_{r_multiple:.2f}"]
        if time_eff > TIME_EFFICIENCY_SLOW:
            factors.append("slow_execution")
        if not regime_aligned:
            factors.append("regime_misaligned")
        if slippage_pct > SLIPPAGE_OK:
            factors.append("high_slippage")
        return "D", factors
