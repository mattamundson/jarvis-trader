"""
OptionsMarketModule — automated premium selling via IB Gateway.
Reuses existing engine/options/ code for chain data and execution.
Uses IB Gateway (same account as futures, paper port 4002).
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

from .auto_roller import OptionsAutoRoller
from .risk import OptionsRiskManager
from .scanner import OptionsScanner
from .strategy_pipeline import OptionsStrategyPipeline

logger = logging.getLogger("jarvis_trader.markets.options")


class OptionsMarketModule(MarketModule):
    """
    Automated options premium-selling module.
    Runs iron condors and credit spreads on SPY/QQQ/IWM using IB Gateway.
    """

    market_name = "options"
    daily_target: float = 125.0
    capital_allocated: float = 50000.0

    def __init__(
        self,
        ib_gateway: "IBGatewayManager",
        underlyings: Optional[list[str]] = None,
        contracts_per_trade: int = 1,
        data_manager=None,
    ):
        self._ib = ib_gateway
        self._scanner = OptionsScanner(
            underlyings=underlyings, data_manager=data_manager
        )
        self._strategy = OptionsStrategyPipeline(contracts_per_trade=contracts_per_trade)
        self._roller = OptionsAutoRoller()
        self._risk = OptionsRiskManager()
        self._status = MarketStatus.OFFLINE
        self._positions: list[Position] = []
        self._daily_pnl: float = 0.0
        self._last_cycle_at: Optional[datetime] = None

    async def connect(self) -> bool:
        """Options uses same IB Gateway as futures — just check connection."""
        try:
            if self._ib.is_connected():
                self._status = MarketStatus.PAPER
                logger.info("Options: IB Gateway connected (shared with futures)")
                return True
            success = await self._ib.connect()
            if success:
                self._status = MarketStatus.PAPER
            return success
        except Exception as exc:
            logger.error(f"Options connect error: {exc}")
            self._status = MarketStatus.ERROR
            return False

    async def get_positions(self) -> list[Position]:
        return self._positions

    async def get_daily_pnl(self) -> float:
        return self._daily_pnl

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """Scan for opportunities, evaluate existing positions, generate signals."""
        if self._status == MarketStatus.HALTED:
            return []

        self._last_cycle_at = datetime.utcnow()
        signals = []

        try:
            # 1. Evaluate existing positions (auto-roller)
            for pos in self._positions:
                # In a real implementation, look up current debit-to-close from IB
                # For now, placeholder
                logger.debug(f"Options: checking position {pos.symbol}")

            # 2. Scan for new opportunities (paper mode — signals generated but not auto-executed)
            scan_results = await self._scanner.scan_async()
            specs = self._strategy.generate(scan_results)

            for spec in specs:
                signal = TradeSignal(
                    symbol=spec.symbol,
                    action="sell_spread",
                    quantity=1,
                    confidence=0.7,
                    strategy=spec.strategy,
                    market=self.market_name,
                    reason=spec.reason,
                    params={
                        "expiry": spec.expiry,
                        "legs": list(spec.legs),
                        "credit_target": spec.credit_target,
                        "max_loss": spec.max_loss,
                    },
                )
                signals.append(signal)
                logger.info(f"Options signal: {spec.strategy} on {spec.symbol} | {spec.reason}")

        except Exception as exc:
            logger.error(f"Options strategy cycle error: {exc}")

        return signals

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """Execute an options trade via IB Gateway (paper mode)."""
        logger.info(
            f"Options: paper trade signal — {signal.symbol} {signal.strategy} (not executed in paper mode)"
        )
        return TradeResult(
            signal=signal,
            executed=False,
            fill_price=None,
            fill_qty=None,
            realized_pnl=None,
            order_id=None,
            error="Paper mode: options execution pending live validation",
        )

    async def shutdown(self) -> None:
        self._status = MarketStatus.OFFLINE
        logger.info("Options module shut down")

    def health_check(self) -> HealthStatus:
        connected = False
        try:
            connected = self._ib.is_connected()
        except Exception:
            pass

        return HealthStatus(
            market=self.market_name,
            status=MarketStatus.PAPER if connected else MarketStatus.OFFLINE,
            message=f"IB Gateway {'connected' if connected else 'disconnected'} | {len(self._positions)} positions",
            daily_pnl=self._daily_pnl,
            open_positions=len(self._positions),
            last_trade_at=self._last_cycle_at,
        )

    def is_enabled(self) -> bool:
        try:
            from config import settings

            return "options" in settings.get_enabled_markets()
        except Exception:
            return False
