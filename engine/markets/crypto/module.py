"""
CryptoMarketModule — BTC/ETH trading via Freqtrade bridge.

Architecture:
  Freqtrade runs as a SEPARATE process at localhost:8080.
  This module polls its REST API for trade status and P&L.
  Strategies live in infrastructure/freqtrade/strategies/.

Enable: CRYPTO_ENABLED=True in .env
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

from .freqtrade_bridge import FreqtradeBridge
from .risk import CryptoRiskManager

logger = logging.getLogger("jarvis_trader.markets.crypto")


class CryptoMarketModule(MarketModule):
    """
    Delegates all crypto trading to a running Freqtrade instance.
    This module is a thin adapter: monitors status, aggregates P&L,
    and provides kill-switch capability (stop/start Freqtrade).
    """

    market_name = "crypto"
    daily_target: float = 100.0
    capital_allocated: float = 15000.0

    def __init__(
        self,
        freqtrade_url: str = "http://localhost:8080/api/v1",
        freqtrade_password: str = "",
    ):
        self._bridge = FreqtradeBridge(base_url=freqtrade_url, password=freqtrade_password)
        self._risk = CryptoRiskManager(total_capital=self.capital_allocated)
        self._status = MarketStatus.OFFLINE
        self._daily_pnl: float = 0.0
        self._cached_positions: list[Position] = []
        self._last_cycle_at: Optional[datetime] = None

    def is_enabled(self) -> bool:
        try:
            from config import settings

            return settings.CRYPTO_ENABLED and "crypto" in settings.get_enabled_markets()
        except Exception:
            return False

    async def connect(self) -> bool:
        """Verify Freqtrade instance is running and authenticate."""
        if not self.is_enabled():
            logger.info("Crypto: disabled (CRYPTO_ENABLED=False)")
            return False

        try:
            running = await self._bridge.is_running()
            if not running:
                logger.warning("Crypto: Freqtrade not running at " + self._bridge.base_url)
                self._status = MarketStatus.ERROR
                return False

            auth_ok = await self._bridge.authenticate()
            if auth_ok:
                self._status = MarketStatus.PAPER
                logger.info("Crypto: Freqtrade bridge connected")
            else:
                self._status = MarketStatus.ERROR

            return auth_ok
        except Exception as exc:
            logger.error(f"Crypto connect error: {exc}")
            self._status = MarketStatus.ERROR
            return False

    async def get_positions(self) -> list[Position]:
        """Return open crypto trades from Freqtrade."""
        try:
            trades = await self._bridge.get_trades()
            positions = []
            for t in trades:
                positions.append(
                    Position(
                        symbol=t.get("pair", "").replace("/", ""),
                        quantity=float(t.get("amount", 0)),
                        avg_cost=float(t.get("open_rate", 0)),
                        market_value=float(t.get("current_value", 0)),
                        unrealized_pnl=float(t.get("profit_abs", 0)),
                        side="long",
                        market=self.market_name,
                        opened_at=None,
                    )
                )
            self._cached_positions = positions
            return positions
        except Exception as exc:
            logger.error(f"Crypto get_positions error: {exc}")
            return self._cached_positions

    async def get_daily_pnl(self) -> float:
        """Return daily P&L from Freqtrade profit endpoint."""
        try:
            profit = await self._bridge.get_profit()
            # profit_all_coin is total profit, profit_today not always available
            today_pnl = float(profit.get("profit_today_abs", profit.get("profit_all_fiat", 0)))
            self._daily_pnl = today_pnl
            return today_pnl
        except Exception as exc:
            logger.error(f"Crypto get_daily_pnl error: {exc}")
            return self._daily_pnl

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """
        Freqtrade manages its own strategy loop internally.
        This method just refreshes our cached state.
        Returns empty list — no direct signal generation from jarvis-trader side.
        """
        if self._status == MarketStatus.HALTED:
            return []

        self._last_cycle_at = datetime.utcnow()
        try:
            await self.get_positions()  # Refresh position cache
            await self.get_daily_pnl()  # Refresh P&L
        except Exception as exc:
            logger.error(f"Crypto cycle refresh error: {exc}")

        return []

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """Crypto signals are handled internally by Freqtrade."""
        return TradeResult(
            signal=signal,
            executed=False,
            fill_price=None,
            fill_qty=None,
            realized_pnl=None,
            order_id=None,
            error="Crypto trades managed by Freqtrade internally",
        )

    async def shutdown(self) -> None:
        """Stop Freqtrade trading loop and close connection."""
        try:
            await self._bridge.stop_trading()
            await self._bridge.close()
            self._status = MarketStatus.OFFLINE
            logger.info("Crypto: Freqtrade stopped")
        except Exception as exc:
            logger.error(f"Crypto shutdown error: {exc}")

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            market=self.market_name,
            status=self._status,
            message=f"Freqtrade @ {self._bridge.base_url} | {len(self._cached_positions)} active trades",
            daily_pnl=self._daily_pnl,
            open_positions=len(self._cached_positions),
            last_trade_at=self._last_cycle_at,
        )
