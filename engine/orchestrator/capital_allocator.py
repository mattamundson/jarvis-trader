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

    def rebalance(self, paper_performance_by_symbol: dict[str, dict]) -> dict[str, float]:
        """
        Reallocate capital based on 30-day Sharpe ratio per instrument.

        Args:
            paper_performance_by_symbol: {symbol: {"sharpe": float, "current_allocation": float}}

        Returns:
            {symbol: new_allocation_fraction} — values sum to 1.0 across active symbols.

        Rules:
        - DO_NOT_TRADE instruments (MCL, MNQ, MGC) → always zeroed out
        - Sharpe > 1.5 → increase allocation by 10% (cap at 50% of total)
        - Sharpe < 0.5 → decrease allocation by 10% (floor at 10% of total)
        - Otherwise → keep current allocation unchanged
        - Renormalize so all active allocations sum to 1.0
        """
        # Single source of truth for what may not trade: the live gate is
        # backtest.signals.DO_NOT_TRADE_SYMBOLS (consumed by the pipeline and
        # safety layer). Import it here instead of keeping a private list — a
        # divergent local copy is the third-config split-brain the MNQ wiring
        # leak taught us to forbid (see tests/test_paper_config_donottrade_sync.py).
        # The old private literal {"MCL","MNQ","MGC"} was wrong both ways: it
        # blocked MGC (gate-v2 PASS, tradeable) and allowed M2K (blocked). Lazy
        # import mirrors pipeline.py / pipeline_autonomous.py and avoids pulling
        # the heavy signals module (numpy/pandas/indicators) at allocator import.
        from backtest.signals import DO_NOT_TRADE_SYMBOLS as _DO_NOT_TRADE

        new_alloc: dict[str, float] = {}
        for symbol, perf in paper_performance_by_symbol.items():
            current: float = float(perf.get("current_allocation", 0.25))
            sharpe: float = float(perf.get("sharpe", 0.0))

            if symbol in _DO_NOT_TRADE:
                new_alloc[symbol] = 0.0
                logger.info("[CapitalAllocator] %s zeroed — DO_NOT_TRADE", symbol)
            elif sharpe > 1.5:
                adjusted = min(current * 1.10, 0.50)
                new_alloc[symbol] = adjusted
                logger.info(
                    "[CapitalAllocator] %s Sharpe=%.2f > 1.5 → allocation %.1f%% → %.1f%%",
                    symbol,
                    sharpe,
                    current * 100,
                    adjusted * 100,
                )
            elif sharpe < 0.5:
                adjusted = max(current * 0.90, 0.10)
                new_alloc[symbol] = adjusted
                logger.info(
                    "[CapitalAllocator] %s Sharpe=%.2f < 0.5 → allocation %.1f%% → %.1f%%",
                    symbol,
                    sharpe,
                    current * 100,
                    adjusted * 100,
                )
            else:
                new_alloc[symbol] = current
                logger.debug(
                    "[CapitalAllocator] %s Sharpe=%.2f in normal range — allocation unchanged %.1f%%",
                    symbol,
                    sharpe,
                    current * 100,
                )

        # Renormalize active (non-zero) allocations to sum to 1.0
        total: float = sum(new_alloc.values())
        if total > 0:
            new_alloc = {k: v / total for k, v in new_alloc.items()}

        self._last_rebalance = datetime.now()
        logger.info("[CapitalAllocator] Rebalance complete: %s", new_alloc)
        return new_alloc

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
