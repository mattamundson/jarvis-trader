"""
JARVIS TRADER — Greeks-Aware Risk Model (Phase 5.3)
==================================================
Monitors portfolio-wide Greeks (Delta, Gamma, Vega, Theta).
Blocks trades that push the portfolio outside defined risk bounds.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger("jarvis_trader.risk.greeks")

@dataclass
class PortfolioGreeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0

class GreeksGuard:
    def __init__(
        self,
        max_delta: float = 100.0,
        max_gamma: float = 10.0,
        max_vega: float = 50.0,
        min_theta: float = -20.0
    ):
        self.max_delta = max_delta
        self.max_gamma = max_gamma
        self.max_vega = max_vega
        self.min_theta = min_theta

    def validate_trade(self, current_greeks: PortfolioGreeks, trade_greeks: PortfolioGreeks) -> Dict[str, Any]:
        """
        Check if a trade's Greeks would exceed portfolio limits.
        """
        new_delta = current_greeks.delta + trade_greeks.delta
        new_gamma = current_greeks.gamma + trade_greeks.gamma
        new_vega = current_greeks.vega + trade_greeks.vega
        new_theta = current_greeks.theta + trade_greeks.theta

        reasons = []
        if abs(new_delta) > self.max_delta:
            reasons.append(f"Delta ({new_delta:.2f}) exceeds limit ({self.max_delta})")
        if abs(new_gamma) > self.max_gamma:
            reasons.append(f"Gamma ({new_gamma:.2f}) exceeds limit ({self.max_gamma})")
        if abs(new_vega) > self.max_vega:
            reasons.append(f"Vega ({new_vega:.2f}) exceeds limit ({self.max_vega})")
        if new_theta < self.min_theta:
            reasons.append(f"Theta ({new_theta:.2f}) below limit ({self.min_theta})")

        return {
            "allowed": len(reasons) == 0,
            "reasons": reasons,
            "projected_greeks": {
                "delta": new_delta,
                "gamma": new_gamma,
                "vega": new_vega,
                "theta": new_theta
            }
        }
