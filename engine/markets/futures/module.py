"""
FuturesMarketModule — thin adapter over existing TradingPipeline + IB Gateway.

Wraps the existing jarvis-trader futures infrastructure (TradingPipeline,
IBGatewayManager, PortfolioTracker, SafetyLayer) into the MarketModule ABC.
Does NOT rebuild any existing logic — just adapts the interface.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from markets.base import (
    HealthStatus,
    MarketModule,
    MarketStatus,
    Position,
    TradeResult,
    TradeSignal,
)

if TYPE_CHECKING:
    from execution.ib_gateway import IBGatewayManager
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

logger = logging.getLogger("jarvis_trader.markets.futures")


class FuturesMarketModule(MarketModule):
    """
    Adapts the existing futures trading infrastructure to the MarketModule interface.

    The existing TradingPipeline handles all signal generation logic.
    This module wraps it, providing lifecycle management and P&L reporting
    to the MultiMarketOrchestrator.
    """

    market_name = "futures"
    daily_target: float = 150.0
    capital_allocated: float = 10000.0

    def __init__(
        self,
        ib_gateway: "IBGatewayManager",
        portfolio_tracker: "PortfolioTracker",
        safety_layer: "SafetyLayer",
        trading_pipeline=None,
        symbols: Optional[list[str]] = None,
    ):
        self._ib = ib_gateway
        self._tracker = portfolio_tracker
        self._safety = safety_layer
        self._pipeline = trading_pipeline
        self._symbols = symbols or ["MES", "MNQ"]
        self._status = MarketStatus.OFFLINE
        self._last_cycle_at: Optional[datetime] = None
        self._daily_pnl: float = 0.0

    async def connect(self) -> bool:
        """Connect to IB Gateway (paper mode only)."""
        try:
            if self._ib.is_connected():
                self._status = MarketStatus.PAPER
                logger.info("Futures: already connected to IB Gateway")
                return True

            success = await self._ib.connect()
            if success:
                self._status = MarketStatus.PAPER
                logger.info("Futures: connected to IB Gateway (paper)")
            else:
                self._status = MarketStatus.ERROR
            return success
        except Exception as exc:
            logger.error(f"Futures connect error: {exc}")
            self._status = MarketStatus.ERROR
            return False

    async def get_positions(self) -> list[Position]:
        """Return open futures positions from PortfolioTracker."""
        try:
            raw_positions = self._tracker.get_open_positions()
            positions = []
            for p in raw_positions:
                positions.append(
                    Position(
                        symbol=p.get("symbol", ""),
                        quantity=float(p.get("quantity", p.get("contracts", 0))),
                        avg_cost=float(p.get("avg_cost", p.get("entry_price", 0))),
                        market_value=float(p.get("market_value", 0)),
                        unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                        side="long"
                        if float(p.get("quantity", p.get("contracts", 0))) > 0
                        else "short",
                        market=self.market_name,
                    )
                )
            return positions
        except Exception as exc:
            logger.error(f"Futures get_positions error: {exc}")
            return []

    async def get_daily_pnl(self) -> float:
        """Return today's P&L from PortfolioTracker."""
        try:
            perf = self._tracker.get_performance()
            # get_performance() returns dict with total_pnl, win_rate, profit_factor
            self._daily_pnl = float(perf.get("today_pnl", perf.get("total_pnl", 0)))
            return self._daily_pnl
        except Exception as exc:
            logger.error(f"Futures get_daily_pnl error: {exc}")
            return 0.0

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """
        Run one iteration of the futures strategy pipeline.
        Returns empty list — signal generation is handled internally by TradingPipeline.
        The pipeline executes trades directly via its own flow.
        """
        if self._status == MarketStatus.HALTED:
            return []

        try:
            self._last_cycle_at = datetime.utcnow()
            # TradingPipeline manages its own execution loop
            # We report "0 signals" since pipeline handles execution internally
            if self._pipeline:
                logger.debug("Futures: TradingPipeline cycle delegated internally")
            return []
        except Exception as exc:
            logger.error(f"Futures strategy cycle error: {exc}")
            return []

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """Execute a futures signal (currently handled by TradingPipeline internally)."""
        return TradeResult(
            signal=signal,
            executed=False,
            fill_price=None,
            fill_qty=None,
            realized_pnl=None,
            order_id=None,
            error="Direct execution not implemented — use TradingPipeline",
        )

    async def shutdown(self) -> None:
        """Disconnect from IB Gateway."""
        try:
            self._status = MarketStatus.OFFLINE
            if self._ib.is_connected():
                await self._ib.disconnect()
                logger.info("Futures: disconnected from IB Gateway")
        except Exception as exc:
            logger.error(f"Futures shutdown error: {exc}")

    def health_check(self) -> HealthStatus:
        """Return current health status."""
        connected = False
        try:
            connected = self._ib.is_connected()
        except Exception:
            pass

        if connected:
            status = MarketStatus.PAPER
        elif self._status == MarketStatus.HALTED:
            status = MarketStatus.HALTED
        else:
            status = MarketStatus.OFFLINE

        return HealthStatus(
            market=self.market_name,
            status=status,
            message=f"IB Gateway {'connected' if connected else 'disconnected'} | Paper mode",
            daily_pnl=self._daily_pnl,
            last_trade_at=self._last_cycle_at,
            open_positions=len(self._tracker.get_open_positions()),
        )

    def halt(self, reason: str = "") -> None:
        """Halt this market module."""
        self._status = MarketStatus.HALTED
        logger.warning(f"Futures halted: {reason}")
