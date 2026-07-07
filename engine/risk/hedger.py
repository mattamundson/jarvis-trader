"""
JARVIS TRADER — Cross-Asset Portfolio Hedger (Phase 8.3)
======================================================
Monitors portfolio-wide beta correlation and macro threats.
Generates hedging recommendations or automatically scales down exposure.

Implements Roadmap P8.3.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger("jarvis_trader.risk.hedger")

# Beta Correlation Groups
EQUITY_GROUP = ["MES", "MNQ", "MYM", "SPY", "QQQ", "AAPL", "MSFT"]
CRYPTO_GROUP = ["BTCUSD", "ETHUSD"]
INFLATION_GROUP = ["MGC", "MCL", "SI"]

@dataclass
class HedgingAction:
    action: str # "scale_down" | "open_hedge" | "hold"
    symbol: str
    quantity: int
    reason: str
    urgency: str # "high" | "medium" | "low"

class PortfolioHedger:
    def __init__(self, db_manager):
        self.db = db_manager

    def evaluate_hedging(
        self,
        portfolio: Dict[str, Any],
        analyst_reports: Dict[str, Any]
    ) -> List[HedgingAction]:
        """
        Evaluate if portfolio requires hedging based on correlation and macro.
        """
        actions = []
        positions = portfolio.get("positions", [])
        if not positions:
            return []

        # 1. Detect High-Beta Overlap (Equity + Crypto)
        equity_exposure = sum(p.get("unrealized_pnl", 0) for p in positions if p["symbol"] in EQUITY_GROUP)
        crypto_exposure = sum(p.get("unrealized_pnl", 0) for p in positions if p["symbol"] in CRYPTO_GROUP)

        # 2. Check Macro Threats (Fed NLP)
        news = analyst_reports.get("news", {})
        is_hawkish = "HAWKISH" in str(news.get("summary", "")).upper() or "FED" in str(news.get("event_type", "")).upper()

        # 3. Check Visual Reversals (Vision Analyst)
        vision = analyst_reports.get("vision", {})
        is_reversal = vision.get("visual_verdict") == "REJECTED" or "Double Top" in str(vision.get("patterns_detected", ""))

        # 4. Logic: High Beta + Macro Threat -> Scale Down
        if (equity_exposure > 0 or crypto_exposure > 0) and (is_hawkish or is_reversal):
            reason = "High-Beta Correlation Spike + "
            reason += "Hawkish Fed detected" if is_hawkish else "Visual Reversal detected"

            # Recommendation: Scale down the largest correlated long
            correlated_longs = [p for p in positions if p["symbol"] in (EQUITY_GROUP + CRYPTO_GROUP) and p.get("quantity", 0) > 0]
            if correlated_longs:
                largest = max(correlated_longs, key=lambda p: p.get("quantity", 0))
                actions.append(HedgingAction(
                    action="scale_down",
                    symbol=largest["symbol"],
                    quantity=max(1, int(largest["quantity"] * 0.5)),
                    reason=reason,
                    urgency="high"
                ))

        return actions

    def get_correlation_scaling_factor(self, symbol: str, portfolio: Dict[str, Any]) -> float:
        """
        Returns a multiplier (0.5 to 1.0) to reduce trade size if symbol
        adds too much correlated risk.
        """
        positions = portfolio.get("positions", [])
        if not positions:
            return 1.0

        # Simple grouping check
        group = None
        if symbol in EQUITY_GROUP:
            group = EQUITY_GROUP
        elif symbol in CRYPTO_GROUP:
            group = CRYPTO_GROUP
        elif symbol in INFLATION_GROUP:
            group = INFLATION_GROUP

        if not group:
            return 1.0

        # Count existing positions in same group
        group_count = sum(1 for p in positions if p["symbol"] in group)

        if group_count >= 2:
            # Already 2+ positions in group, scale down new entries by 50%
            return 0.5

        return 1.0
