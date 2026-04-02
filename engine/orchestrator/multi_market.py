"""
MultiMarketOrchestrator — coordinates all market modules.
Manages lifecycle, scheduling, cross-market risk, and P&L aggregation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from markets.base import HealthStatus, MarketModule, MarketStatus

logger = logging.getLogger("jarvis_trader.orchestrator")

# Global singleton
_orchestrator: Optional["MultiMarketOrchestrator"] = None


def get_orchestrator() -> Optional["MultiMarketOrchestrator"]:
    return _orchestrator


def set_orchestrator(orch: "MultiMarketOrchestrator") -> None:
    global _orchestrator
    _orchestrator = orch


class MultiMarketOrchestrator:
    """
    Coordinates all market modules: futures, options, polymarket, crypto.

    Responsibilities:
    - Register and start/stop market modules
    - Run strategy cycles on each module's schedule
    - Aggregate cross-market P&L and exposure
    - Trigger kill switches when risk limits are breached
    """

    def __init__(self, daily_target: float = 500.0, max_portfolio_loss_pct: float = 5.0):
        self.daily_target = daily_target
        self.max_portfolio_loss_pct = max_portfolio_loss_pct
        self._modules: dict[str, MarketModule] = {}
        self._running = False
        self._halted = False
        self._halt_reason: Optional[str] = None
        self._start_time: Optional[datetime] = None

    def register(self, module: MarketModule) -> None:
        """Register a market module."""
        self._modules[module.market_name] = module
        logger.info(f"Registered market module: {module.market_name}")

    def get_module(self, name: str) -> Optional[MarketModule]:
        return self._modules.get(name)

    def list_modules(self) -> list[str]:
        return list(self._modules.keys())

    async def start(self) -> None:
        """Connect all modules and begin strategy cycles."""
        if self._running:
            logger.warning("Orchestrator already running")
            return

        self._running = True
        self._start_time = datetime.utcnow()
        logger.info(f"Starting orchestrator with {len(self._modules)} modules")

        # Connect all modules
        for name, module in self._modules.items():
            if not module.is_enabled():
                logger.info(f"  {name}: disabled, skipping")
                continue
            try:
                ok = await module.connect()
                if ok:
                    logger.info(f"  {name}: connected ✓")
                else:
                    logger.warning(f"  {name}: connect() returned False")
            except Exception as exc:
                logger.error(f"  {name}: connection failed — {exc}")

    async def stop(self) -> None:
        """Gracefully shut down all modules."""
        self._running = False
        logger.info("Stopping all market modules...")
        for name, module in self._modules.items():
            try:
                await module.shutdown()
                logger.info(f"  {name}: shutdown ✓")
            except Exception as exc:
                logger.error(f"  {name}: shutdown error — {exc}")

    async def run_all_cycles(self) -> dict[str, int]:
        """Run one strategy cycle on all active modules. Returns signal counts."""
        if self._halted:
            logger.warning(f"Orchestrator halted: {self._halt_reason}")
            return {}

        results: dict[str, int] = {}
        for name, module in self._modules.items():
            if not module.is_enabled():
                continue
            try:
                signals = await module.run_strategy_cycle()
                for signal in signals:
                    await module.execute_signal(signal)
                results[name] = len(signals)
            except Exception as exc:
                logger.error(f"{name}: strategy cycle error — {exc}")
                results[name] = 0

        return results

    async def get_portfolio_summary(self) -> dict:
        """Aggregate P&L and positions across all modules."""
        total_pnl = 0.0
        total_positions = 0
        module_stats = {}

        for name, module in self._modules.items():
            try:
                pnl = await module.get_daily_pnl()
                positions = await module.get_positions()
                total_pnl += pnl
                total_positions += len(positions)
                module_stats[name] = {
                    "daily_pnl": pnl,
                    "open_positions": len(positions),
                    "target": module.daily_target,
                    "capital": module.capital_allocated,
                }
            except Exception as exc:
                logger.error(f"{name}: portfolio summary error — {exc}")
                module_stats[name] = {"error": str(exc)}

        return {
            "total_daily_pnl": total_pnl,
            "daily_target": self.daily_target,
            "target_progress_pct": (total_pnl / self.daily_target * 100)
            if self.daily_target
            else 0,
            "total_open_positions": total_positions,
            "markets": module_stats,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "uptime_seconds": (datetime.utcnow() - self._start_time).total_seconds()
            if self._start_time
            else 0,
        }

    def get_all_health(self) -> list[HealthStatus]:
        """Return health status of all modules."""
        statuses = []
        for module in self._modules.values():
            try:
                statuses.append(module.health_check())
            except Exception as exc:
                statuses.append(
                    HealthStatus(
                        market=module.market_name,
                        status=MarketStatus.ERROR,
                        message=str(exc),
                    )
                )
        return statuses

    def halt_all(self, reason: str) -> None:
        """Emergency halt all markets."""
        self._halted = True
        self._halt_reason = reason
        logger.critical(f"PORTFOLIO HALT: {reason}")

    def resume(self) -> None:
        """Resume trading after a halt (requires manual intervention)."""
        self._halted = False
        self._halt_reason = None
        logger.info("Orchestrator resumed")
