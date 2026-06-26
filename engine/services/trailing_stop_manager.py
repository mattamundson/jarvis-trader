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

# ATR period (14-bar, 1h) and timeframe must match the backtest assumption.
_ATR_PERIOD = 14
_ATR_TIMEFRAME = "1h"
# Lookback in days needed to compute 14-bar 1h ATR with margin.
_ATR_LOOKBACK_DAYS = 3


def _compute_atr_from_df(df, period: int = _ATR_PERIOD) -> float | None:
    """
    Return the most-recent ATR value from an OHLCV DataFrame.

    Uses JesseIndicators (pandas_ta) so the computation matches the backtester.
    Returns None if the DataFrame is empty or lacks required columns.
    """
    required = {"high", "low", "close"}
    if df is None or df.empty or not required.issubset(df.columns):
        return None

    try:
        from analysis.jesse_indicators import JesseIndicators

        atr_arr = JesseIndicators.atr(
            df["high"].values, df["low"].values, df["close"].values, period=period
        )
        if atr_arr is None or len(atr_arr) == 0:
            return None
        # Take the last non-NaN value.
        import numpy as np

        valid = atr_arr[~np.isnan(atr_arr)]
        return float(valid[-1]) if len(valid) > 0 else None
    except Exception as exc:
        logger.warning(f"[TrailingStop] ATR computation failed: {exc}")
        return None


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

        # Read the multiplier from config once at construction so it can be
        # overridden at test time without touching the environment.
        try:
            from config import settings

            self._atr_mult = settings.TRAILING_STOP_ATR_MULT
        except Exception:
            self._atr_mult = 2.0  # safe hard-coded fallback if config unavailable

    async def start(self):
        """Start the monitoring loop."""
        if self._running:
            return

        self._running = True
        logger.info(
            f"TrailingStopManager: Monitoring active trades every {self.interval}s "
            f"(ATR mult={self._atr_mult})"
        )
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("TrailingStopManager: Stopped")

    async def _run_loop(self):
        """Main loop."""
        while self._running:
            try:
                await self._process_active_trades()
            except Exception as e:
                logger.error(f"[TrailingStop] Loop error: {e}")

            await asyncio.sleep(self.interval)

    async def _get_atr(self, symbol: str, current_price: float) -> float:
        """
        Return ATR for *symbol* using 14-period 1h bars from the data manager.

        Safety rail: if bars are unavailable (data source down, insufficient
        history, computation error) falls back to 0.5 % of current price —
        the original proxy — so the stop is always set to a non-zero distance.
        """
        proxy = current_price * 0.005
        try:
            df = await self.data.get_bars(
                symbol, lookback_days=_ATR_LOOKBACK_DAYS, timeframe=_ATR_TIMEFRAME
            )
            atr = _compute_atr_from_df(df, period=_ATR_PERIOD)
            if atr and atr > 0:
                return atr
        except Exception as exc:
            logger.warning(f"[TrailingStop] get_bars failed for {symbol}: {exc}")

        logger.debug(
            f"[TrailingStop] Using ATR proxy for {symbol}: {proxy:.4f} "
            f"(real ATR unavailable)"
        )
        return proxy

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

            # 2. Get ATR — real 14-bar 1h value; falls back to 0.5% proxy.
            atr = await self._get_atr(trade.symbol, current_price)

            # 3. Calculate new trail using the config-driven multiplier.
            mult = self._atr_mult

            if trade.quantity > 0:  # LONG
                new_stop = current_price - (mult * atr)
                if trade.stop_loss_price is None or new_stop > trade.stop_loss_price:
                    # Move stop up
                    await self.oms.update_stop_loss(trade.trade_id, new_stop)
            elif trade.quantity < 0:  # SHORT
                new_stop = current_price + (mult * atr)
                if trade.stop_loss_price is None or new_stop < trade.stop_loss_price:
                    # Move stop down
                    await self.oms.update_stop_loss(trade.trade_id, new_stop)
