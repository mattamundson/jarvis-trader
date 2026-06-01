"""
JARVIS TRADER — Strategy Ensemble Router
Routes incoming signals to the appropriate strategy logic based on current market regime.
Handles conflict resolution and portfolio exposure caps.
"""

from __future__ import annotations

import logging
from typing import List

from backtest.regime_classifier import MarketRegime

logger = logging.getLogger("jarvis_trader.strategy_router")

class StrategyRouter:
    """
    Orchestrates the multi-strategy system.

    Mapping (per Battle Plan):
    - TREND    -> Strategy A (Trend Following)
    - MEANREV  -> Strategy B (Mean Reversion)
    - RANGE    -> All (Scale Down)
    - VOLATILE -> Shadow Only
    - CRISIS   -> Exits Only / Safety Override
    """

    def __init__(
        self,
        max_concurrent_positions: int = 3,
        max_margin_utilization: float = 0.30,
    ):
        self._max_positions = max_concurrent_positions
        self._max_margin = max_margin_utilization

    def route_decision(
        self,
        symbol: str,
        regime: MarketRegime,
        raw_decision: dict,
        active_positions: List[str],
    ) -> dict:
        """
        Adjusts the trade decision based on regime and portfolio state.

        Returns a modified decision dict.
        """
        action = raw_decision.get("final_action", "hold").lower()

        # 1. Portfolio Exposure Check
        if action in ["buy", "sell"] and len(active_positions) >= self._max_positions:
            if symbol not in active_positions:
                logger.warning(f"[Router] Portfolio full ({len(active_positions)}/{self._max_positions}). Vetoing {symbol} entry.")
                return self._veto(raw_decision, f"Portfolio capacity limit ({self._max_positions})")

        # 2. Regime Routing
        if regime == MarketRegime.CRISIS:
            if action in ["buy", "sell"] and symbol not in active_positions:
                return self._veto(raw_decision, "Regime=CRISIS. New entries blocked.")

        elif regime == MarketRegime.VOLATILE:
            # Downgrade to Shadow Mode if not already a high-confidence signal
            confidence = raw_decision.get("trade_decision", {}).get("confidence", 0)
            if confidence < 0.85:
                logger.info(f"[Router] Regime=VOLATILE and confidence {confidence} < 0.85. Diverting to Shadow Mode.")
                return self._to_shadow(raw_decision, "High volatility shadow mandate")

        elif regime == MarketRegime.RANGE:
            # Reduce quantity for ranging markets
            qty = raw_decision.get("final_quantity", 0)
            if qty > 1:
                new_qty = max(1, int(qty * 0.5))
                raw_decision["final_quantity"] = new_qty
                logger.info(f"[Router] Regime=RANGE. Scaled quantity {qty} -> {new_qty}")

        return raw_decision

    def _veto(self, decision: dict, reason: str) -> dict:
        decision["final_action"] = "hold"
        decision["final_quantity"] = 0
        decision["router_veto"] = reason
        decision["reasoning"] = f"{decision.get('reasoning', '')}\n[ROUTER VETO]: {reason}"
        return decision

    def _to_shadow(self, decision: dict, reason: str) -> dict:
        decision["is_shadow"] = True
        decision["router_note"] = reason
        return decision
