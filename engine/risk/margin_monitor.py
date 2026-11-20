"""
JARVIS TRADER — Margin Monitor Agent
Proactively monitors IBKR account margin and portfolio drawdown.
Triggers alerts and safety overrides if institutional-grade risk limits are breached.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.margin_monitor")

class MarginMonitorAgent:
    """
    Monitors account health metrics:
    - Margin Utilization (Current / Max)
    - Drawdown from Peak Equity
    - Daily P&L vs Kill-Switch Threshold
    """

    def __init__(
        self,
        connector,
        utilization_warning: float = 0.25,
        utilization_halt: float = 0.35,
        max_drawdown_pct: float = 8.0,
        pnl_monitor=None,
    ):
        self._connector = connector
        self._util_warning = utilization_warning
        self._util_halt = utilization_halt
        self._max_dd_pct = max_drawdown_pct

        # 2026-09-10 drawdown metric-source reconciliation: when a PnLMonitor is
        # injected, drawdown_pct is sourced from its persisted 90-day high-water
        # mark so MarginMonitor and AlertManager report the same number across
        # engine restarts. Falls back to the legacy in-process peak when absent,
        # preserving standalone/default behavior exactly.
        self._pnl_monitor = pnl_monitor
        self._peak_equity = 0.0
        self._current_metrics: Dict[str, float] = {}
        self._last_check: Optional[datetime] = None

    async def check_health(self) -> Dict[str, Any]:
        """
        Fetch latest account data and evaluate health.
        """
        if self._connector is None:
            return {"status": "SKIPPED", "message": "No broker connector configured"}

        summary = await self._fetch_account_snapshot()
        if summary is None:
            return {
                "status": "SKIPPED",
                "message": "Broker connector does not expose account health metrics",
            }
        if not summary:
            return {"status": "ERROR", "message": "Could not fetch account summary"}

        equity = float(summary.get("equity", 0.0))
        buying_power = float(summary.get("buying_power", 0.0))

        # Calculate Utilization
        # Rough proxy: 1 / (BuyingPower / Equity) assuming 4:1 max
        # or more directly if MarginUsed is available
        margin_used = float(summary.get("margin_used", 0.0))
        utilization = 0.0
        if buying_power > 0:
            # IB Buying power is often 4x Excess Liquidity for stocks,
            # for futures it varies by SPAN.
            # We'll use (Equity - Excess) / Equity as utilization if available.
            utilization = margin_used / equity if equity > 0 else 0.0

        # Update Peak and Drawdown
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = 0.0
        if self._pnl_monitor is not None:
            # Single metric source: use the persisted 90-day high-water mark from
            # PnLMonitor so this surface matches AlertManager across restarts.
            persisted_peak = 0.0
            try:
                persisted_peak = float(self._pnl_monitor.get_peak_balance())
            except Exception as exc:
                logger.warning(
                    "[MarginMonitor] persisted peak read failed (%s); "
                    "falling back to in-process peak",
                    exc,
                )
            if persisted_peak > 0:
                drawdown = (persisted_peak - equity) / persisted_peak * 100
            elif self._peak_equity > 0:
                drawdown = (self._peak_equity - equity) / self._peak_equity * 100
        elif self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity * 100

        self._current_metrics = {
            "equity": equity,
            "utilization": utilization,
            "drawdown_pct": drawdown,
            "buying_power": buying_power,
            "timestamp": datetime.now().isoformat(),
        }
        self._last_check = datetime.now()

        # Evaluate Status
        status = "HEALTHY"
        message = "All systems green."

        if utilization >= self._util_halt:
            status = "CRITICAL"
            message = f"MARGIN UTILIZATION {utilization:.1%} EXCEEDS HALT THRESHOLD {self._util_halt:.1%}"
        elif utilization >= self._util_warning:
            status = "WARNING"
            message = f"Margin utilization {utilization:.1%} entering warning zone."

        if drawdown >= self._max_dd_pct:
            status = "CRITICAL"
            message = f"DRAWDOWN {drawdown:.1f}% EXCEEDS MAX LIMIT {self._max_dd_pct}%"

        logger.info(
            "[MarginMonitor] Status: %s | Equity: $%.2f | Util: %.1f%% | DD: %.1f%%",
            status,
            equity,
            utilization * 100.0,
            drawdown,
        )

        return {
            "status": status,
            "message": message,
            "metrics": self._current_metrics
        }

    async def _fetch_account_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        Fetch account health metrics from the connected broker/data adapter.

        Some connectors expose ``get_account_summary()`` while lighter paper/data
        adapters only expose ``get_account_balance()``. Accept either shape and
        normalize to a dict the monitor can consume.
        """
        get_account_summary = getattr(self._connector, "get_account_summary", None)
        if callable(get_account_summary):
            return await get_account_summary()

        get_account_balance = getattr(self._connector, "get_account_balance", None)
        if callable(get_account_balance):
            return await get_account_balance()

        return None

    async def run_loop(self, interval_seconds: int = 60):
        """Monitor in a background loop."""
        while True:
            try:
                await self.check_health()
            except Exception as e:
                logger.error("[MarginMonitor] Loop error: %s", e)
            await asyncio.sleep(interval_seconds)
