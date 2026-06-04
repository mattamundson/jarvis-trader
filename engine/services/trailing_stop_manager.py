"""
JARVIS TRADER — Trailing Stop Manager (Phase 5.3)
================================================
Background service that monitors active trades and adjusts broker-side 
stop-loss orders as price moves in favor of the trade.

Uses ATR-based trailing logic from the backtester.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("jarvis_trader.trailing_stop")

# Flag (read fresh each evaluation): when "1", trail on real ATRr_14 computed
# from recent bars; otherwise use the legacy 0.5%-of-price proxy. Default off so
# the change is inert until Amo A/Bs it in paper.
_REAL_ATR_FLAG = "TRAILING_STOP_USE_REAL_ATR"
# Proxy fraction retained as the warm-up / no-data fallback (was the only path).
_ATR_PROXY_FRAC = 0.005


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

    @staticmethod
    def _real_atr_enabled() -> bool:
        return os.environ.get(_REAL_ATR_FLAG, "0").strip() == "1"

    async def _compute_atr(self, symbol: str) -> Optional[float]:
        """Compute ATRr_14 from recent bars, mirroring TechnicalAnalystAgent.

        Returns the ATR value, or None when bars are unavailable/insufficient so
        the caller can fall back to the proxy. Never raises — any failure logs at
        debug and yields None. pandas/pandas_ta imported lazily to keep the
        service import cheap.
        """
        try:
            df = await self.data.get_bars(
                symbol, lookback_days=5, timeframe="5m", is_futures=True
            )
        except Exception as exc:
            logger.debug("[TrailingStop] get_bars failed for %s: %s", symbol, exc)
            return None

        if df is None or getattr(df, "empty", True) or len(df) < 2:
            return None
        if not {"high", "low", "close"}.issubset(df.columns):
            return None

        try:
            import pandas as pd
            import pandas_ta  # noqa: F401 — registers the df.ta accessor

            df.ta.atr(append=True)
            if "ATRr_14" in df and not pd.isna(df["ATRr_14"].iloc[-1]):
                return float(df["ATRr_14"].iloc[-1])

            # Fallback: simple True Range mean when pandas_ta needs more warmup.
            hi, lo, cl = df["high"], df["low"], df["close"]
            tr = pd.concat(
                [hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1
            ).max(axis=1)
            period = min(14, len(tr) - 1)
            return float(tr.iloc[-period:].mean()) if period > 0 else None
        except Exception as exc:
            logger.debug("[TrailingStop] ATR compute failed for %s: %s", symbol, exc)
            return None

    async def _resolve_atr(self, symbol: str, current_price: float) -> float:
        """Real ATR when enabled+computable, else the 0.5%-of-price proxy."""
        proxy = current_price * _ATR_PROXY_FRAC
        if not self._real_atr_enabled():
            return proxy
        real = await self._compute_atr(symbol)
        if real is None or real <= 0:
            logger.info(
                "[TrailingStop] %s real ATR unavailable — using proxy %.4f", symbol, proxy
            )
            return proxy
        logger.info("[TrailingStop] %s using real ATRr_14=%.4f (proxy was %.4f)", symbol, real, proxy)
        return real

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

            # 2. Get ATR for the symbol. With TRAILING_STOP_USE_REAL_ATR=1 this
            # computes ATRr_14 from recent bars (same logic as the technical
            # analyst); otherwise — and on any warm-up/no-data case — it falls
            # back to the legacy 0.5%-of-price proxy.
            atr = await self._resolve_atr(trade.symbol, current_price)
            
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
