"""
PolymarketScanner — find liquid markets with mispriced odds.
Identifies markets where YES + NO ≠ $1.00 (arbitrage) or spread is wide (market making).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger("jarvis_trader.markets.polymarket.scanner")

MIN_VOLUME_24H = 1000.0    # Min $1K daily volume for liquidity
MAX_SPREAD_PCT = 0.05      # Max 5% spread for market making
ARB_THRESHOLD = 0.02       # Flag arb if YES+NO sum deviates > 2% from $1


@dataclass
class PolymarketOpportunity:
    token_id: str
    question: str
    yes_price: float
    no_price: float
    volume_24h: float
    spread: float
    opportunity_type: str  # "market_making" | "arb" | "event_driven"
    confidence: float
    notes: str = ""
    scanned_at: datetime = None

    def __post_init__(self):
        if self.scanned_at is None:
            self.scanned_at = datetime.utcnow()

    @property
    def implied_sum(self) -> float:
        return self.yes_price + self.no_price

    @property
    def arb_deviation(self) -> float:
        return abs(1.0 - self.implied_sum)


class PolymarketScanner:
    """
    Scans Polymarket for trading opportunities.
    Three strategies: market making, arbitrage (YES+NO ≠ 1), event-driven.
    """

    def __init__(self, client=None, min_volume: float = MIN_VOLUME_24H):
        self._client = client
        self.min_volume = min_volume

    def scan(self) -> list[PolymarketOpportunity]:
        """Scan all active markets and return opportunities."""
        if not self._client or not self._client.is_connected():
            logger.debug("Polymarket scanner: no live client, returning empty results")
            return []

        opportunities = []
        try:
            markets = self._client.get_markets(active_only=True)
            for market in markets:
                opp = self._evaluate_market(market)
                if opp:
                    opportunities.append(opp)
        except Exception as exc:
            logger.error(f"Polymarket scan error: {exc}")

        logger.info(f"Polymarket scan: {len(opportunities)} opportunities found")
        return opportunities

    def _evaluate_market(self, market: dict) -> Optional[PolymarketOpportunity]:
        """Evaluate one market for trading opportunity."""
        try:
            volume = float(market.get("volume24hr", 0))
            if volume < self.min_volume:
                return None

            token_ids = market.get("tokens", [])
            if len(token_ids) < 2:
                return None

            yes_price = float(market.get("bestAsk", 0.5))
            no_price = float(market.get("bestBid", 0.5))
            question = market.get("question", "")
            token_id = token_ids[0].get("token_id", "")

            spread = abs(yes_price - no_price)
            implied_sum = yes_price + no_price
            arb_dev = abs(1.0 - implied_sum)

            # Arbitrage opportunity
            if arb_dev > ARB_THRESHOLD:
                return PolymarketOpportunity(
                    token_id=token_id,
                    question=question,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume_24h=volume,
                    spread=spread,
                    opportunity_type="arb",
                    confidence=min(arb_dev * 10, 0.9),
                    notes=f"YES+NO = {implied_sum:.3f} (deviate {arb_dev:.3f} from 1.0)",
                )

            # Market making (wide spread, liquid market)
            if spread > 0.02 and volume > self.min_volume * 2:
                return PolymarketOpportunity(
                    token_id=token_id,
                    question=question,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume_24h=volume,
                    spread=spread,
                    opportunity_type="market_making",
                    confidence=0.6,
                    notes=f"Spread {spread:.3f}, volume ${volume:,.0f}",
                )

            return None
        except Exception as exc:
            logger.debug(f"_evaluate_market error: {exc}")
            return None
