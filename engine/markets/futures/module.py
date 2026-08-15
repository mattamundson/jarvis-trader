"""
FuturesMarketModule — thin adapter over existing TradingPipeline + IB Gateway.

Wraps the existing jarvis-trader futures infrastructure (TradingPipeline,
IBGatewayManager, PortfolioTracker, SafetyLayer) into the MarketModule ABC.
Does NOT rebuild any existing logic — just adapts the interface.
"""

from __future__ import annotations

import asyncio
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
    from data.market_data import MarketDataManager
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
        data_manager: "Optional[MarketDataManager]" = None,
    ):
        self._ib = ib_gateway
        self._tracker = portfolio_tracker
        self._safety = safety_layer
        self._pipeline = trading_pipeline
        self._symbols = symbols or ["MES", "MNQ"]
        self._status = MarketStatus.OFFLINE
        self._last_cycle_at: Optional[datetime] = None
        self._daily_pnl: float = 0.0
        # Live-quote source for mark-to-market unrealized P&L in get_positions().
        # Optional so existing callers/tests that construct this module without
        # a data_manager keep the prior (dict-passthrough) behavior unchanged.
        self._data_manager = data_manager

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
        """Return open futures positions from PortfolioTracker.

        ``unrealized_pnl`` / ``market_value`` are recomputed live (mark-to-market)
        from the current price at READ time when a data_manager is wired in —
        never trusted from a static field on the raw position dict. The raw
        dicts coming out of ``PortfolioTracker.get_open_positions()`` never
        carry an ``unrealized_pnl``/``market_value`` key at all (those fields
        only exist on the separate, IBKR-sync-populated ``get_positions()``
        path), so the previous ``p.get("unrealized_pnl", 0)`` silently posted
        a flat 0.0 for every open position regardless of how far price had
        moved. Recomputation reuses the exact same live-quote fetch +
        mark-to-market formula (including the suspect-entry/suspect-mark/
        stale-mark guards) that ``/portfolio/summary`` and ``/portfolio/paper/
        positions/unrealized`` already use, so every surface agrees on one
        number. Falls back to whatever's on the raw dict when no data_manager
        is available (tests, or data-manager-less construction) so behavior
        is unchanged in that case.

        Positions are sourced via ``get_open_positions_authoritative()``
        (DB-reconciled) rather than the raw in-memory ``get_open_positions()``
        read: the in-memory ``_open`` map can drift from the ``paper_trades``
        table when a row is written by a path that bypasses the tracker (the
        stop-monitor's ``db_manager.close_trade`` fallback, or a peer process),
        which is what let ``/portfolio/health`` and ``/portfolio/summary``
        disagree on ``open_positions`` for the same account. The live recompute
        below then runs on the reconciled list.
        """
        try:
            raw_positions, _recon = self._tracker.get_open_positions_authoritative()
        except Exception as exc:
            logger.error(f"Futures get_positions error: {exc}")
            return []

        if not raw_positions:
            return []

        computed_by_key: dict[str, dict] = {}
        if self._data_manager is not None:
            try:
                from routers.portfolio_router import _compute_unrealized
                from utils.position_sizing import INSTRUMENT_MULTIPLIERS as _POINT_VALUES

                symbols = [str(p.get("symbol", "")) for p in raw_positions]
                price_results = await asyncio.gather(
                    *[self._data_manager.get_current_price(sym) for sym in symbols],
                    return_exceptions=True,
                )
                for p, price_result in zip(raw_positions, price_results, strict=True):
                    if isinstance(price_result, Exception):
                        logger.warning(
                            "Futures get_positions: live price fetch failed for %s: %s",
                            p.get("symbol"),
                            price_result,
                        )
                        continue
                    current_price = (
                        price_result.get("last_price") if isinstance(price_result, dict) else None
                    )
                    mark_source = (
                        price_result.get("source") if isinstance(price_result, dict) else None
                    )
                    computed = _compute_unrealized(
                        p, current_price, _POINT_VALUES, mark_source=mark_source
                    )
                    key = str(p.get("trade_id") or p.get("symbol"))
                    computed_by_key[key] = computed
            except Exception as exc:
                logger.warning(
                    "Futures get_positions: live mark-to-market failed, falling back to "
                    "stored position values: %s",
                    exc,
                )

        positions = []
        for p in raw_positions:
            key = str(p.get("trade_id") or p.get("symbol"))
            computed = computed_by_key.get(key)
            quantity = float(p.get("quantity", p.get("contracts", 0)))
            if computed is not None and computed.get("unrealized_pnl") is not None:
                unrealized_pnl = float(computed["unrealized_pnl"])
                current_price = computed.get("current_price")
                symbol_key = str(p.get("symbol", "")).upper()
                multiplier = _POINT_VALUES.get(symbol_key, _POINT_VALUES.get("DEFAULT", 1.0))
                market_value = (
                    abs(quantity) * float(current_price) * multiplier
                    if current_price is not None
                    else float(p.get("market_value", 0))
                )
            else:
                # No live mark available (no data_manager, fetch failed, or the
                # computed mark was rejected as suspect/stale) — preserve the
                # prior passthrough behavior rather than fabricating a number.
                unrealized_pnl = float(p.get("unrealized_pnl", 0))
                market_value = float(p.get("market_value", 0))
            positions.append(
                Position(
                    symbol=p.get("symbol", ""),
                    quantity=quantity,
                    avg_cost=float(p.get("avg_cost", p.get("entry_price", 0))),
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    side="long" if quantity > 0 else "short",
                    market=self.market_name,
                )
            )
        return positions

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
        """Return current health status.

        ``open_positions`` is read via ``get_open_positions_authoritative()``
        (DB-reconciled) — the same source ``get_positions()`` now uses — so this
        count can never disagree with ``/portfolio/summary``'s
        ``total_open_positions``. Previously this called the raw in-memory
        ``get_open_positions()`` directly with no exception guard, so any
        transient error here (unlike the guarded call in ``get_positions()``)
        propagated to ``MultiMarketOrchestrator.get_all_health()``, which
        swallows it and substitutes a bare ``HealthStatus(status=ERROR)`` whose
        ``open_positions`` silently defaults to 0 — surfacing a phantom "flat"
        reading on the dashboard while real positions were still open.
        """
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

        try:
            open_positions, _recon = self._tracker.get_open_positions_authoritative()
            open_count = len(open_positions)
        except Exception as exc:
            logger.error(f"Futures health_check: open-position read failed: {exc}")
            open_count = 0

        return HealthStatus(
            market=self.market_name,
            status=status,
            message=f"IB Gateway {'connected' if connected else 'disconnected'} | Paper mode",
            daily_pnl=self._daily_pnl,
            last_trade_at=self._last_cycle_at,
            open_positions=open_count,
        )

    def halt(self, reason: str = "") -> None:
        """Halt this market module."""
        self._status = MarketStatus.HALTED
        logger.warning(f"Futures halted: {reason}")
