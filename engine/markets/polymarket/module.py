"""
PolymarketModule — prediction market trading via Polymarket CLOB API.

IMPORTANT: Polymarket has U.S. regulatory restrictions (CFTC settled 2022).
This module is DISABLED by default (POLYMARKET_ENABLED=False).
Consider Kalshi (CFTC-regulated) as an alternative.

Enable only after reviewing applicable regulations.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from markets.base import (
    HealthStatus,
    MarketModule,
    MarketStatus,
    Position,
    TradeResult,
    TradeSignal,
)

from .client import PolymarketClient
from .risk import PolymarketRiskManager
from .scanner import PolymarketScanner
from .strategies import ArbitrageStrategy, MarketMakingStrategy

logger = logging.getLogger("jarvis_trader.markets.polymarket")


class PolymarketModule(MarketModule):
    """
    Prediction market trading on Polymarket.
    Uses py-clob-client for CLOB API access.
    USDC settlement on Polygon (Ethereum L2).
    """

    market_name = "polymarket"
    daily_target: float = 125.0
    capital_allocated: float = 20000.0

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        private_key: str = "",
        order_size_usdc: float = 50.0,
    ):
        self._client = PolymarketClient(api_key=api_key, api_secret=api_secret, private_key=private_key)
        self._scanner = PolymarketScanner(client=self._client)
        self._mm_strategy = MarketMakingStrategy(order_size_usdc=order_size_usdc)
        self._arb_strategy = ArbitrageStrategy(order_size_usdc=order_size_usdc * 2)
        self._risk = PolymarketRiskManager(total_capital=self.capital_allocated)
        self._status = MarketStatus.OFFLINE
        self._daily_pnl: float = 0.0
        self._open_positions: list = []
        self._last_cycle_at: Optional[datetime] = None

    def is_enabled(self) -> bool:
        try:
            from config import settings
            return settings.POLYMARKET_ENABLED and "polymarket" in settings.get_enabled_markets()
        except Exception:
            return False

    async def connect(self) -> bool:
        """Connect to Polymarket CLOB API."""
        if not self.is_enabled():
            logger.info("Polymarket: disabled (POLYMARKET_ENABLED=False)")
            return False

        success = self._client.connect()
        if success:
            self._status = MarketStatus.PAPER  # Paper until validated
            logger.info("Polymarket: connected to CLOB API")
        else:
            self._status = MarketStatus.ERROR
        return success

    async def get_positions(self) -> list[Position]:
        """Return open prediction market positions."""
        positions = []
        for p in self._open_positions:
            positions.append(Position(
                symbol=p.get("token_id", "")[:20],
                quantity=float(p.get("size", 0)),
                avg_cost=float(p.get("entry_price", 0)),
                market_value=float(p.get("current_value", 0)),
                unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                side="long",
                market=self.market_name,
            ))
        return positions

    async def get_daily_pnl(self) -> float:
        return self._daily_pnl

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """Scan Polymarket and generate trading signals."""
        if not self.is_enabled() or self._status == MarketStatus.HALTED:
            return []

        self._last_cycle_at = datetime.utcnow()
        signals = []

        try:
            opportunities = self._scanner.scan()
            if not opportunities:
                return []

            # Market making signals
            mm_signals = self._mm_strategy.generate(opportunities)
            # Arbitrage signals
            arb_signals = self._arb_strategy.generate(opportunities)

            all_poly_signals = mm_signals + arb_signals
            for ps in all_poly_signals:
                signal = TradeSignal(
                    symbol=ps.token_id[:20],
                    action=ps.side,
                    quantity=ps.size_usdc,
                    confidence=ps.confidence,
                    strategy=ps.strategy,
                    market=self.market_name,
                    reason=ps.reason,
                    params={"price": ps.price, "question": ps.question},
                )
                signals.append(signal)

        except Exception as exc:
            logger.error(f"Polymarket strategy cycle error: {exc}")

        return signals

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """Execute a Polymarket signal (paper mode until validated)."""
        logger.info(f"Polymarket: paper signal — {signal.action} ${signal.quantity:.0f} on {signal.symbol}")
        return TradeResult(
            signal=signal,
            executed=False,
            fill_price=signal.params.get("price"),
            fill_qty=None,
            realized_pnl=None,
            order_id=None,
            error="Paper mode: Polymarket execution pending regulatory review and live validation",
        )

    async def shutdown(self) -> None:
        self._status = MarketStatus.OFFLINE
        logger.info("Polymarket module shut down")

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            market=self.market_name,
            status=self._status if self._client.is_connected() else MarketStatus.OFFLINE,
            message=f"CLOB {'connected' if self._client.is_connected() else 'disconnected'} | "
                    f"{len(self._open_positions)} positions | Regulatory note: U.S. gray area",
            daily_pnl=self._daily_pnl,
            open_positions=len(self._open_positions),
            last_trade_at=self._last_cycle_at,
        )
