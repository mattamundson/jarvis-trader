"""
CorrelationMonitor — tracks directional exposure across markets.
Blocks new positions when total directional exposure exceeds 30%.
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger("jarvis_trader.orchestrator.correlation")

MAX_DIRECTIONAL_EXPOSURE_PCT = 0.30  # 30% of total capital


class CorrelationMonitor:
    """
    Simple directional exposure tracker.
    Tracks net long/short as fraction of total capital.
    Flags when correlated exposure is too high.
    """

    def __init__(
        self, total_capital: float, max_directional_pct: float = MAX_DIRECTIONAL_EXPOSURE_PCT
    ):
        self.total_capital = total_capital
        self.max_directional_pct = max_directional_pct
        self._net_exposure: dict[str, float] = defaultdict(float)  # market → net $ exposure

    def update(self, market: str, net_exposure_usd: float) -> None:
        """Update net exposure for a market (positive = long, negative = short)."""
        self._net_exposure[market] = net_exposure_usd

    def total_net_exposure(self) -> float:
        return sum(self._net_exposure.values())

    def total_net_exposure_pct(self) -> float:
        if self.total_capital <= 0:
            return 0.0
        return abs(self.total_net_exposure()) / self.total_capital

    def is_overexposed(self) -> bool:
        return self.total_net_exposure_pct() > self.max_directional_pct

    def get_status(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "net_exposure_usd": self.total_net_exposure(),
            "net_exposure_pct": round(self.total_net_exposure_pct() * 100, 2),
            "max_directional_pct": round(self.max_directional_pct * 100, 2),
            "overexposed": self.is_overexposed(),
            "by_market": dict(self._net_exposure),
        }
