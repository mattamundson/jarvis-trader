"""
Avellaneda-Stoikov Market Making
================================
A professional market making strategy that adjusts bid/ask spreads
based on inventory risk and market volatility.
"""

import logging
from datetime import datetime
from typing import Dict, Tuple

import numpy as np

logger = logging.getLogger("jarvis_trader.strategies.mm.avellaneda")

class AvellanedaStoikovStrategy:
    def __init__(
        self,
        gamma: float = 0.1,     # Risk aversion parameter
        sigma: float = 0.01,    # Volatility (standard deviation of returns)
        T: float = 1.0,         # Total time (e.g., 1 trading day)
        k: float = 1.5,         # Order book liquidity parameter
        A: float = 140.0        # Order book density parameter
    ):
        self.gamma = gamma
        self.sigma = sigma
        self.T = T
        self.k = k
        self.A = A

    def calculate_quotes(
        self,
        mid_price: float,
        inventory: int,
        time_elapsed: float,
        news_sentiment: float = 0.0 # -1.0 to 1.0 (from FinGPT analyst)
    ) -> Tuple[float, float]:
        """
        Calculate optimal bid and ask prices.

        :param mid_price: Current market mid-price
        :param inventory: Current number of shares held
        :param time_elapsed: Current time in session (0-1)
        :param news_sentiment: Sentiment bias from news analysis
        :return: (bid_price, ask_price)
        """
        # 1. Calculate Reservation Price (neutral price based on inventory risk)
        # Shift the reservation price even more if news sentiment is strong
        time_remaining = self.T - time_elapsed
        sentiment_shift = news_sentiment * (self.sigma ** 2) * time_remaining
        reservation_price = mid_price - (inventory * self.gamma * (self.sigma ** 2) * time_remaining) + sentiment_shift

        # 2. Calculate Optimal Spread
        # spread = (2 / gamma) * ln(1 + (gamma / k))
        # Note: In some versions, spread also depends on time_remaining
        optimal_spread = (self.gamma * (self.sigma ** 2) * time_remaining) + \
                         (2 / self.gamma) * np.log(1 + (self.gamma / self.k))

        # 3. Calculate Bid and Ask
        bid_price = reservation_price - (optimal_spread / 2)
        ask_price = reservation_price + (optimal_spread / 2)

        return round(bid_price, 2), round(ask_price, 2)

    def on_tick(self, market_data: Dict, current_inventory: int, session_start: datetime, news_sentiment: float = 0.0):
        """
        Execute strategy logic on every price tick.
        """
        mid_price = market_data.get('mid_price')
        if not mid_price:
            return None

        # Calculate time elapsed (normalized 0.0 to 1.0 for a trading day)
        now = datetime.now()
        elapsed = (now - session_start).total_seconds() / (6.5 * 3600) # Assuming 6.5h session
        elapsed = min(max(elapsed, 0.0), 1.0)

        bid, ask = self.calculate_quotes(mid_price, current_inventory, elapsed, news_sentiment)

        logger.info(f"MM: Mid={mid_price:.2f} Inv={current_inventory} -> Bid={bid:.2f} Ask={ask:.2f}")

        return {
            "bid": bid,
            "ask": ask,
            "side": "BOTH",
            "reasoning": f"Avellaneda-Stoikov: reservation_price centered at inventory {current_inventory}"
        }
