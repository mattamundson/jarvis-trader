"""
Polymarket trading strategies.
Three strategies:
  1. MarketMaking — bid/ask spread capture (0% maker fee)
  2. EventDriven — LLM probability vs market odds
  3. Arbitrage — YES + NO sum ≠ $1.00
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .scanner import PolymarketOpportunity

logger = logging.getLogger("jarvis_trader.markets.polymarket.strategies")

# Market making: post limit orders at bid+spread/2 and ask-spread/2
MAKER_SPREAD_CAPTURE_PCT = 0.40  # Capture 40% of observed spread


@dataclass
class PolymarketSignal:
    token_id: str
    question: str
    side: str  # "buy_yes" | "buy_no" | "make_bid" | "make_ask"
    price: float
    size_usdc: float
    strategy: str
    confidence: float
    reason: str


class MarketMakingStrategy:
    """
    Posts resting limit orders at mid±spread/2 to capture maker fee (0%).
    Only operates on markets with volume > threshold.
    """

    def __init__(self, order_size_usdc: float = 50.0, spread_capture: float = MAKER_SPREAD_CAPTURE_PCT):
        self.order_size_usdc = order_size_usdc
        self.spread_capture = spread_capture

    def generate(self, opportunities: list[PolymarketOpportunity]) -> list[PolymarketSignal]:
        signals = []
        for opp in [o for o in opportunities if o.opportunity_type == "market_making"]:
            mid = (opp.yes_price + opp.no_price) / 2
            half_capture = opp.spread * self.spread_capture / 2

            # Bid slightly above best bid
            signals.append(PolymarketSignal(
                token_id=opp.token_id,
                question=opp.question[:60],
                side="make_bid",
                price=round(mid - half_capture, 3),
                size_usdc=self.order_size_usdc,
                strategy="market_making",
                confidence=opp.confidence,
                reason=f"MM bid on spread {opp.spread:.3f}",
            ))

            # Ask slightly below best ask
            signals.append(PolymarketSignal(
                token_id=opp.token_id,
                question=opp.question[:60],
                side="make_ask",
                price=round(mid + half_capture, 3),
                size_usdc=self.order_size_usdc,
                strategy="market_making",
                confidence=opp.confidence,
                reason=f"MM ask on spread {opp.spread:.3f}",
            ))

        return signals


class EventDrivenStrategy:
    """
    Buys YES/NO based on LLM probability estimate vs market implied probability.
    Requires NewsAnalystAgent (already in jarvis-trader) for prediction.
    """

    def __init__(self, min_edge_pct: float = 0.10, order_size_usdc: float = 100.0):
        self.min_edge_pct = min_edge_pct  # Minimum 10% edge to trade
        self.order_size_usdc = order_size_usdc

    def generate(self, opportunities: list[PolymarketOpportunity], llm_predictions: Optional[dict] = None) -> list[PolymarketSignal]:
        """
        Compare LLM predictions (token_id → probability) with market prices.
        If edge > min_edge_pct, generate a signal.
        """
        if not llm_predictions:
            return []

        signals = []
        for opp in [o for o in opportunities if o.opportunity_type in ("market_making", "event_driven")]:
            pred = llm_predictions.get(opp.token_id)
            if pred is None:
                continue

            edge = abs(pred - opp.yes_price)
            if edge < self.min_edge_pct:
                continue

            if pred > opp.yes_price:
                signals.append(PolymarketSignal(
                    token_id=opp.token_id,
                    question=opp.question[:60],
                    side="buy_yes",
                    price=opp.yes_price,
                    size_usdc=self.order_size_usdc,
                    strategy="event_driven",
                    confidence=min(edge * 5, 0.85),
                    reason=f"LLM p={pred:.2f} vs market {opp.yes_price:.2f} (edge {edge:.2f})",
                ))
            else:
                signals.append(PolymarketSignal(
                    token_id=opp.token_id,
                    question=opp.question[:60],
                    side="buy_no",
                    price=opp.no_price,
                    size_usdc=self.order_size_usdc,
                    strategy="event_driven",
                    confidence=min(edge * 5, 0.85),
                    reason=f"LLM p={pred:.2f} vs market {opp.yes_price:.2f} (edge {edge:.2f})",
                ))

        return signals


class ArbitrageStrategy:
    """
    Buys both YES and NO when YES + NO < $1.00 (locked-in profit).
    Only safe arb — no correlation risk.
    """

    def __init__(self, min_arb_profit_usdc: float = 2.0, order_size_usdc: float = 100.0):
        self.min_arb_profit_usdc = min_arb_profit_usdc
        self.order_size_usdc = order_size_usdc

    def generate(self, opportunities: list[PolymarketOpportunity]) -> list[PolymarketSignal]:
        signals = []
        for opp in [o for o in opportunities if o.opportunity_type == "arb"]:
            if opp.implied_sum >= 1.0:
                continue  # Only trade when sum < 1.0

            profit_per_unit = 1.0 - opp.implied_sum
            contracts = self.order_size_usdc / opp.yes_price
            expected_profit = contracts * profit_per_unit

            if expected_profit < self.min_arb_profit_usdc:
                continue

            signals.append(PolymarketSignal(
                token_id=opp.token_id,
                question=opp.question[:60],
                side="buy_yes",
                price=opp.yes_price,
                size_usdc=self.order_size_usdc / 2,
                strategy="arbitrage",
                confidence=0.95,
                reason=f"ARB: YES+NO={opp.implied_sum:.3f} < 1.00, profit ~${expected_profit:.2f}",
            ))
            signals.append(PolymarketSignal(
                token_id=opp.token_id,
                question=opp.question[:60],
                side="buy_no",
                price=opp.no_price,
                size_usdc=self.order_size_usdc / 2,
                strategy="arbitrage",
                confidence=0.95,
                reason=f"ARB: YES+NO={opp.implied_sum:.3f} < 1.00, profit ~${expected_profit:.2f}",
            ))

        return signals
