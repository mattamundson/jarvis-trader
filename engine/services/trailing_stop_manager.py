"""
JARVIS TRADER — Trailing Stop Manager (Phase 5.3)
================================================
Background service that monitors active trades and adjusts broker-side
stop-loss orders as price moves in favor of the trade.

Uses ATR-based trailing logic from the backtester.
"""

import asyncio
import logging

logger = logging.getLogger("jarvis_trader.trailing_stop")

class TrailingStopManager:
    """
    Monitors OMS active trades and moves stops.
    """

    def __init__(self, oms_manager, data_manager, interval_sec: int = 60):
        self.oms = oms_manager
        self.data = data_manager
        self.interval = interval_sec
        self._running = False
        self._task = None

    async def start(self):
        """Start the monitoring loop."""
        if self._running:
            return

        self._running = True
        logger.info(f"🛡️ TrailingStopManager: Monitoring active trades every {self.interval}s")
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("🛑 TrailingStopManager: Stopped")

    async def _run_loop(self):
        """Main loop."""
        while self._running:
            try:
                await self._process_active_trades()
            except Exception as e:
                logger.error(f"[TrailingStop] Loop error: {e}")

            await asyncio.sleep(self.interval)

    async def _process_active_trades(self):
        """
        Fetch active trades from OMS and evaluate stop updates.
        """
        active_trades = self.oms.active_trades.values()
        if not active_trades:
            return

        for trade in active_trades:
            if trade.status.value != "active":
                continue

            # 1. Get latest price
            tick = await self.data.get_tick_price(trade.symbol)
            current_price = tick.get("last_price")
            if not current_price:
                continue

            # 2. Get ATR for the symbol (fallback to 1% of price if unavailable)
            # In a real run, we'd pull the latest technical analysis report
            # but for now we'll use a conservative estimate or prior ATR.
            # TODO: Link to TechnicalAnalystAgent.last_report
            atr = current_price * 0.005 # 0.5% ATR proxy for now

            # 3. Calculate new trail
            # Logic: move stop UP for longs, DOWN for shorts
            # Params from trend_signals.py: atr_trail_mult = 2.0
            mult = 2.0

            if trade.quantity > 0: # LONG
                new_stop = current_price - (mult * atr)
                if trade.stop_loss_price is None or new_stop > trade.stop_loss_price:
                    # Move stop up
                    await self.oms.update_stop_loss(trade.trade_id, new_stop)
            elif trade.quantity < 0: # SHORT
                new_stop = current_price + (mult * atr)
                if trade.stop_loss_price is None or new_stop < trade.stop_loss_price:
                    # Move stop down
                    await self.oms.update_stop_loss(trade.trade_id, new_stop)
