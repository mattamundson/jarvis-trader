"""
CryptoMarketModule — BTC/ETH trading.

Two supported backends, chosen at construction time via `backend` arg or
the CRYPTO_BACKEND env var (default: "freqtrade"):

  - "freqtrade" — delegate to a running Freqtrade instance at localhost:8080.
    Freqtrade owns strategy + exchange connectivity; this module polls its
    REST API for status and P&L. execute_signal is a no-op since Freqtrade
    runs its own loop.
  - "kraken"    — drive the `kraken-cli` binary directly for spot/futures
    orders via KrakenAdapter. Paper-first by default; live requires
    KRAKEN_LIVE_ENABLED=true AND separate approval per trade.

Enable: CRYPTO_ENABLED=True in .env. Backend switches CRYPTO_BACKEND.
"""

from __future__ import annotations

import logging
import os
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
from .kraken_adapter import KrakenAdapter
from .risk import CryptoRiskManager

logger = logging.getLogger("jarvis_trader.markets.crypto")


def _resolve_backend(explicit: Optional[str]) -> str:
    """Return 'freqtrade' or 'kraken' — whichever was requested or configured."""
    if explicit:
        return explicit.strip().lower()
    return (os.environ.get("CRYPTO_BACKEND") or "freqtrade").strip().lower()


def _live_enabled() -> bool:
    return (os.environ.get("KRAKEN_LIVE_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


class CryptoMarketModule(MarketModule):
    """
    Routes crypto trading to either Freqtrade or Kraken depending on backend
    selection. Keeps a single MarketModule surface area for the orchestrator.
    """

    market_name = "crypto"
    daily_target: float = 100.0
    capital_allocated: float = 15000.0

    def __init__(
        self,
        freqtrade_url: str = "http://localhost:8080/api/v1",
        freqtrade_password: str = "",
        backend: Optional[str] = None,
    ):
        self._backend = _resolve_backend(backend)
        self._freqtrade: Optional[FreqtradeBridge] = None
        self._kraken: Optional[KrakenAdapter] = None

        if self._backend == "kraken":
            self._kraken = KrakenAdapter(live_enabled=_live_enabled())
            logger.info(
                "Crypto backend: kraken (%s)",
                "LIVE" if _live_enabled() else "paper",
            )
        else:
            # Default to Freqtrade; preserves behavior for existing installs.
            self._freqtrade = FreqtradeBridge(
                base_url=freqtrade_url, password=freqtrade_password
            )
            logger.info("Crypto backend: freqtrade")

        self._risk = CryptoRiskManager(total_capital=self.capital_allocated)
        self._status = MarketStatus.OFFLINE
        self._daily_pnl: float = 0.0
        self._cached_positions: list[Position] = []
        self._last_cycle_at: Optional[datetime] = None

    # Exposed for tests and health-check introspection.
    @property
    def backend(self) -> str:
        return self._backend

    @property
    def _bridge(self) -> FreqtradeBridge:
        """
        Back-compat accessor for code that still reads `_bridge` on the
        module. Raises when the active backend is not Freqtrade.
        """
        if self._freqtrade is None:
            raise AttributeError(
                "CryptoMarketModule._bridge is only valid when backend='freqtrade'"
            )
        return self._freqtrade

    @_bridge.setter
    def _bridge(self, value: FreqtradeBridge) -> None:
        """
        Back-compat setter: existing tests inject a mock via
        `module._bridge = mock_freqtrade_bridge`. Assigning here routes the
        value to the internal freqtrade slot so methods branching on backend
        keep working.
        """
        self._freqtrade = value

    def is_enabled(self) -> bool:
        try:
            from config import settings

            return settings.CRYPTO_ENABLED and "crypto" in settings.get_enabled_markets()
        except Exception:
            return False

    async def connect(self) -> bool:
        """Probe whichever backend is active."""
        if not self.is_enabled():
            logger.info("Crypto: disabled (CRYPTO_ENABLED=False)")
            return False

        try:
            if self._backend == "kraken":
                assert self._kraken is not None
                ok = await self._kraken.connect()
                if ok:
                    self._status = (
                        MarketStatus.LIVE if _live_enabled() else MarketStatus.PAPER
                    )
                    logger.info(
                        "Crypto: Kraken adapter connected (%s)",
                        "LIVE" if _live_enabled() else "paper",
                    )
                else:
                    self._status = MarketStatus.ERROR
                    logger.warning("Crypto: Kraken CLI not reachable")
                return ok

            # Freqtrade backend
            assert self._freqtrade is not None
            running = await self._freqtrade.is_running()
            if not running:
                logger.warning(
                    "Crypto: Freqtrade not running at " + self._freqtrade.base_url
                )
                self._status = MarketStatus.ERROR
                return False

            auth_ok = await self._freqtrade.authenticate()
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
        """Return open crypto positions from whichever backend is active."""
        try:
            if self._backend == "kraken":
                assert self._kraken is not None
                raw = await self._kraken.get_positions()
                positions = []
                for p in raw:
                    if not isinstance(p, dict):
                        continue
                    sym = str(p.get("symbol") or p.get("pair") or "").replace("/", "")
                    qty = float(p.get("quantity") or p.get("size") or p.get("amount") or 0)
                    positions.append(
                        Position(
                            symbol=sym,
                            quantity=qty,
                            avg_cost=float(p.get("avg_cost") or p.get("entry_price") or 0),
                            market_value=float(p.get("market_value") or 0),
                            unrealized_pnl=float(p.get("unrealized_pnl") or p.get("pnl") or 0),
                            side="long" if qty >= 0 else "short",
                            market=self.market_name,
                            opened_at=None,
                        )
                    )
                self._cached_positions = positions
                return positions

            # Freqtrade
            assert self._freqtrade is not None
            trades = await self._freqtrade.get_trades()
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
        """Return daily P&L from whichever backend is active."""
        try:
            if self._backend == "kraken":
                assert self._kraken is not None
                pnl = await self._kraken.get_daily_pnl()
                self._daily_pnl = pnl
                return pnl

            assert self._freqtrade is not None
            profit = await self._freqtrade.get_profit()
            today_pnl = float(
                profit.get("profit_today_abs", profit.get("profit_all_fiat", 0))
            )
            self._daily_pnl = today_pnl
            return today_pnl
        except Exception as exc:
            logger.error(f"Crypto get_daily_pnl error: {exc}")
            return self._daily_pnl

    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """
        Refresh cached state. Neither Kraken nor Freqtrade generates
        signals from inside this module — signals originate in the pipeline
        and are handed to `execute_signal`.
        """
        if self._status == MarketStatus.HALTED:
            return []

        self._last_cycle_at = datetime.utcnow()
        try:
            await self.get_positions()
            await self.get_daily_pnl()
        except Exception as exc:
            logger.error(f"Crypto cycle refresh error: {exc}")
        return []

    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """
        Kraken backend: actually submits the order (paper or live depending
        on KRAKEN_LIVE_ENABLED). Freqtrade backend: refuses — Freqtrade owns
        its own trading loop.
        """
        if self._backend == "kraken":
            assert self._kraken is not None
            try:
                limit_price = signal.params.get("limit_price") if signal.params else None
                result = await self._kraken.submit_order(
                    symbol=signal.symbol,
                    side=signal.action,
                    quantity=signal.quantity,
                    order_type=(signal.params or {}).get("order_type"),
                    limit_price=limit_price,
                )
                if result is None:
                    return TradeResult(
                        signal=signal,
                        executed=False,
                        fill_price=None,
                        fill_qty=None,
                        realized_pnl=None,
                        order_id=None,
                        error="kraken submit_order returned no result",
                    )
                fill_price = result.get("fill_price") or result.get("price")
                fill_qty = result.get("fill_qty") or result.get("quantity") or signal.quantity
                return TradeResult(
                    signal=signal,
                    executed=True,
                    fill_price=float(fill_price) if fill_price is not None else None,
                    fill_qty=float(fill_qty) if fill_qty is not None else None,
                    realized_pnl=None,
                    order_id=str(result.get("order_id") or result.get("txid") or ""),
                )
            except Exception as exc:
                logger.error(f"Kraken execute_signal error: {exc}")
                return TradeResult(
                    signal=signal,
                    executed=False,
                    fill_price=None,
                    fill_qty=None,
                    realized_pnl=None,
                    order_id=None,
                    error=str(exc),
                )

        # Freqtrade backend: trades are managed internally.
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
        """Close backend connections. Kraken has no long-lived session."""
        try:
            if self._backend == "kraken":
                # kraken-cli holds no persistent connection — nothing to close.
                self._status = MarketStatus.OFFLINE
                logger.info("Crypto: Kraken adapter shutdown")
                return

            assert self._freqtrade is not None
            await self._freqtrade.stop_trading()
            await self._freqtrade.close()
            self._status = MarketStatus.OFFLINE
            logger.info("Crypto: Freqtrade stopped")
        except Exception as exc:
            logger.error(f"Crypto shutdown error: {exc}")

    def health_check(self) -> HealthStatus:
        if self._backend == "kraken":
            assert self._kraken is not None
            msg = (
                f"Kraken CLI ({'LIVE' if _live_enabled() else 'paper'}) | "
                f"{len(self._cached_positions)} active positions"
            )
        else:
            assert self._freqtrade is not None
            msg = (
                f"Freqtrade @ {self._freqtrade.base_url} | "
                f"{len(self._cached_positions)} active trades"
            )
        return HealthStatus(
            market=self.market_name,
            status=self._status,
            message=msg,
            daily_pnl=self._daily_pnl,
            open_positions=len(self._cached_positions),
            last_trade_at=self._last_cycle_at,
        )
