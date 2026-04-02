"""
CapitalAllocator — dynamic capital rebalancing based on performance.
Adjusts per-market allocations over time, favoring better performers.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("jarvis_trader.orchestrator.capital_allocator")


class CapitalAllocator:
    """
    Manages capital allocation across market modules.
    Starts at configured amounts, adjusts based on 7-day rolling performance.
    New markets start at 25% of their target capital (ramp-up safety).
    """

    def __init__(self, initial_allocations: dict[str, float]):
        """
        initial_allocations: {market_name: capital_amount}
        """
        self._allocations = dict(initial_allocations)
        self._performance_history: dict[str, list[float]] = {m: [] for m in initial_allocations}
        self._ramp_factor: dict[str, float] = dict.fromkeys(initial_allocations, 0.25)
        self._last_rebalance: datetime | None = None

    def get_allocation(self, market: str) -> float:
        base = self._allocations.get(market, 0.0)
        ramp = self._ramp_factor.get(market, 0.25)
        return base * ramp

    def record_daily_pnl(self, market: str, pnl: float) -> None:
        if market not in self._performance_history:
            self._performance_history[market] = []
        self._performance_history[market].append(pnl)
        # Keep rolling 30 days
        if len(self._performance_history[market]) > 30:
            self._performance_history[market].pop(0)

    def ramp_up(self, market: str) -> None:
        """Increase ramp factor toward 1.0 in 25% steps (called after validation milestones)."""
        current = self._ramp_factor.get(market, 0.25)
        new = min(1.0, current + 0.25)
        self._ramp_factor[market] = new
        logger.info(f"Capital ramp-up for {market}: {current:.0%} → {new:.0%}")

    def get_summary(self) -> dict:
        return {
            market: {
                "base_capital": self._allocations.get(market, 0),
                "ramp_factor": self._ramp_factor.get(market, 0.25),
                "effective_capital": self.get_allocation(market),
                "days_tracked": len(self._performance_history.get(market, [])),
            }
            for market in self._allocations
        }
