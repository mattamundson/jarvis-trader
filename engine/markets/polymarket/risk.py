"""
PolymarketRiskManager — position limits and capital controls for prediction markets.
Conservative limits given U.S. regulatory uncertainty.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("jarvis_trader.markets.polymarket.risk")

MAX_POSITION_PCT = 5.0    # Max 5% of Polymarket capital per market
MAX_DEPLOYED_PCT = 60.0   # Max 60% of capital deployed at once
MAX_OPEN_MARKETS = 20     # Max 20 simultaneous open positions


class PolymarketRiskManager:
    """Risk controls specific to Polymarket trading."""

    def __init__(
        self,
        total_capital: float = 20000.0,
        max_position_pct: float = MAX_POSITION_PCT,
        max_deployed_pct: float = MAX_DEPLOYED_PCT,
        max_open_markets: int = MAX_OPEN_MARKETS,
    ):
        self.total_capital = total_capital
        self.max_position_pct = max_position_pct
        self.max_deployed_pct = max_deployed_pct
        self.max_open_markets = max_open_markets

    def max_position_size_usdc(self) -> float:
        return self.total_capital * (self.max_position_pct / 100)

    def check_new_order(
        self,
        order_size_usdc: float,
        current_deployed_usdc: float,
        current_open_markets: int,
    ) -> tuple[bool, str]:
        """
        Check if a new order is within risk limits.
        Returns (approved, reason).
        """
        # Position size limit
        if order_size_usdc > self.max_position_size_usdc():
            return False, f"Order ${order_size_usdc:.0f} > max ${self.max_position_size_usdc():.0f}"

        # Deployed capital limit
        max_deployed = self.total_capital * (self.max_deployed_pct / 100)
        if current_deployed_usdc + order_size_usdc > max_deployed:
            return False, f"Would exceed {self.max_deployed_pct}% deployed capital limit"

        # Open markets limit
        if current_open_markets >= self.max_open_markets:
            return False, f"Max {self.max_open_markets} open markets reached"

        return True, "OK"

    def get_limits(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "max_position_usdc": self.max_position_size_usdc(),
            "max_deployed_usdc": self.total_capital * (self.max_deployed_pct / 100),
            "max_open_markets": self.max_open_markets,
        }
