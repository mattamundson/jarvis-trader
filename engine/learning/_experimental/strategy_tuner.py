"""
Strategy Tuner — US-013
Suggests conservative parameter adjustments based on recent trade performance.
Safety parameters are NEVER modified (Tier 3 only).
"""

import logging
from dataclasses import dataclass

from agents.research_agent import ResearchAgent, StrategyHypothesis, is_research_agent_enabled

logger = logging.getLogger(__name__)

SAFETY_PARAMS = {
    "MAX_POSITION_SIZE_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MAX_DRAWDOWN_PCT",
    "MAX_ORDERS_PER_MINUTE",
    "MAX_CORRELATED_EXPOSURE_PCT",
    "PRICE_COLLAR_PCT",
    "MAX_SINGLE_ORDER_VALUE",
    "MAX_MARGIN_UTILIZATION",
    "MAX_CONTRACTS_PER_INSTRUMENT",
    "MAX_OVERNIGHT_CONTRACTS",
    "CONSECUTIVE_LOSS_HALF_SIZE",
    "CONSECUTIVE_LOSS_QUARTER_SIZE",
    "CONSECUTIVE_LOSS_HALT",
    "LIVE_TRADING_ENABLED",
    "REQUIRE_HUMAN_APPROVAL",
}

TUNABLE_PARAMS = {
    "STC_OS": (10, 20, "int"),
    "STC_OB": (80, 95, "int"),
    "STOP_ATR": (0.5, 1.5, "float"),
    "T1_ATR": (0.8, 2.0, "float"),
    "T2_ATR": (1.5, 3.5, "float"),
    "T3_ATR": (2.0, 5.0, "float"),
    "ATR_PERIOD": (10, 20, "int"),
}

MIN_CONFIDENCE = 0.6
MAX_CHANGE_PCT = 0.10


@dataclass
class Suggestion:
    """A suggested parameter adjustment."""

    param_name: str
    current_value: float
    suggested_value: float
    confidence: float
    reason: str


class StrategyTuner:
    """
    Suggests conservative parameter adjustments based on recent trade results.
    Never suggests changes to safety parameters (those require Tier 3 approval).
    Max 10% change per parameter per cycle to avoid overfit.
    """

    def __init__(self):
        """Initialize tuner."""
        logger.info("StrategyTuner initialized")

    def suggest_adjustments(
        self, recent_trades: list[dict], current_params: dict
    ) -> list[Suggestion]:
        """
        Suggest parameter adjustments based on recent trade performance.

        Args:
            recent_trades: List of recent trade dicts (last 20–30 trades)
            current_params: Current strategy parameters dict

        Returns:
            List of Suggestion objects. Empty if insufficient data or no adjustments recommended.
        """
        if not recent_trades or len(recent_trades) < 5:
            logger.debug("Insufficient trades for suggestions")
            return []

        if not current_params:
            logger.debug("No current params provided")
            return []

        suggestions: list[Suggestion] = []

        try:
            num_trades = len(recent_trades)
            win_rate = sum(1 for t in recent_trades if t.get("won")) / num_trades
            r_multiples = [t.get("pnl", 0) / max(t.get("risk", 1), 1) for t in recent_trades]
            avg_r_multiple = sum(r_multiples) / num_trades

            logger.debug(
                f"Analyzed {num_trades} trades: win_rate={win_rate:.2%}, "
                f"avg_r={avg_r_multiple:.2f}"
            )

            if win_rate < 0.35:
                suggestions.extend(self._suggest_entry_changes(current_params))

            if avg_r_multiple < 0.5:
                suggestions.extend(self._suggest_stop_changes(current_params))

            if win_rate > 0.65:
                suggestions.extend(self._suggest_scaling_changes(current_params))

            logger.info(f"Generated {len(suggestions)} suggestions")
            return suggestions

        except Exception as e:
            logger.exception(f"Error generating suggestions: {e}")
            return []

    def _suggest_entry_changes(self, current_params: dict) -> list[Suggestion]:
        """Suggest changes to entry parameters if win rate is low."""
        suggestions: list[Suggestion] = []

        stc_os = current_params.get("STC_OS", 15)
        if stc_os > 10:
            new_val = max(10, int(stc_os * (1 - MAX_CHANGE_PCT)))
            suggestions.append(
                Suggestion(
                    param_name="STC_OS",
                    current_value=stc_os,
                    suggested_value=new_val,
                    confidence=0.65,
                    reason="Low win rate: raise oversold threshold to filter weak entries",
                )
            )

        stc_ob = current_params.get("STC_OB", 83)
        if stc_ob < 95:
            new_val = min(95, int(stc_ob * (1 + MAX_CHANGE_PCT)))
            suggestions.append(
                Suggestion(
                    param_name="STC_OB",
                    current_value=stc_ob,
                    suggested_value=new_val,
                    confidence=0.65,
                    reason="Low win rate: raise overbought threshold to catch stronger trends",
                )
            )

        return suggestions

    def _suggest_stop_changes(self, current_params: dict) -> list[Suggestion]:
        """Suggest changes to stop loss if R-multiple is low."""
        suggestions: list[Suggestion] = []

        stop_atr = float(current_params.get("STOP_ATR", 0.7))
        if stop_atr > 0.5:
            new_val = max(0.5, stop_atr * (1 - MAX_CHANGE_PCT))
            suggestions.append(
                Suggestion(
                    param_name="STOP_ATR",
                    current_value=stop_atr,
                    suggested_value=round(new_val, 2),
                    confidence=0.70,
                    reason="Low R-multiple: tighten stop to reduce risk per trade",
                )
            )

        t1_atr = float(current_params.get("T1_ATR", 1.0))
        if t1_atr < 2.0:
            new_val = min(2.0, t1_atr * (1 + MAX_CHANGE_PCT))
            suggestions.append(
                Suggestion(
                    param_name="T1_ATR",
                    current_value=t1_atr,
                    suggested_value=round(new_val, 2),
                    confidence=0.65,
                    reason="Low R-multiple: increase T1 target for better reward:risk",
                )
            )

        return suggestions

    def _suggest_scaling_changes(self, current_params: dict) -> list[Suggestion]:
        """Suggest changes when performance is excellent."""
        suggestions: list[Suggestion] = []

        logger.info("High win rate detected. No size scaling suggested (consult trader manually).")

        return suggestions

    def is_safety_param(self, param_name: str) -> bool:
        """Check if a parameter is a safety parameter (immutable)."""
        return param_name in SAFETY_PARAMS

    def is_tunable_param(self, param_name: str) -> bool:
        """Check if a parameter can be tuned."""
        return param_name in TUNABLE_PARAMS

    def clamp_suggestion(self, param_name: str, suggested_value: float) -> float:
        """Clamp a suggested value to valid range."""
        if param_name not in TUNABLE_PARAMS:
            return suggested_value

        min_val, max_val, _ = TUNABLE_PARAMS[param_name]
        return max(min_val, min(max_val, suggested_value))

    async def generate_hypothesis(
        self,
        symbol: str,
        recent_trades: list[dict] | None = None,
        current_params: dict | None = None,
    ) -> StrategyHypothesis | None:
        """Generate a strategy hypothesis via ResearchAgent.

        Off-pipeline path — called after backtest completion or at scheduled
        intervals. Returns None when ENABLE_RESEARCH_AGENT is unset (default).

        Args:
            symbol: e.g. "MES", "MNQ", "MCL".
            recent_trades: optional last-N trade dicts to seed context.
            current_params: optional current strategy params dict.

        Returns:
            A validated StrategyHypothesis, or None if the agent is disabled.
        """
        if not is_research_agent_enabled():
            logger.debug("ResearchAgent disabled (ENABLE_RESEARCH_AGENT not set)")
            return None
        try:
            researcher = ResearchAgent()
            context: dict = {
                "recent_trades": recent_trades or [],
                "current_params": current_params or {},
                "suggestions": (
                    self.suggest_adjustments(recent_trades or [], current_params or {})
                    if (recent_trades is not None and current_params is not None)
                    else []
                ),
                "symbol": symbol,
            }
            hypothesis = await researcher.propose(symbol, context=context)
            logger.info(
                "[ResearchAgent] generated hypothesis %r for %s (confidence=%.2f)",
                hypothesis.name,
                symbol,
                hypothesis.confidence,
            )
            return hypothesis
        except Exception as exc:
            logger.warning("[ResearchAgent] hypothesis generation failed: %s", exc)
            return None
