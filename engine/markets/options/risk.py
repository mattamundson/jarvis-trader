"""
OptionsRiskManager — position-level risk checks for options module.
Enforces: max Greeks exposure, earnings blackout, concentration limits.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger("jarvis_trader.markets.options.risk")

MAX_THETA_DAILY = 500.0  # Max total daily theta decay ($)
MAX_DELTA_TOTAL = 50.0  # Max net delta (share equivalents)
MAX_VEGA_TOTAL = 2000.0  # Max total vega exposure
MAX_POSITION_COUNT = 10  # Max open positions
EARNINGS_BLACKOUT_DAYS = 5  # Avoid opening within N days of earnings


class OptionsRiskCheck:
    """Result of a risk check."""

    def __init__(self, approved: bool, reason: str = ""):
        self.approved = approved
        self.reason = reason


class OptionsRiskManager:
    """
    Validates new options trades against portfolio-level risk limits.
    """

    def __init__(
        self,
        max_theta: float = MAX_THETA_DAILY,
        max_delta: float = MAX_DELTA_TOTAL,
        max_vega: float = MAX_VEGA_TOTAL,
        max_positions: int = MAX_POSITION_COUNT,
        earnings_blackout_days: int = EARNINGS_BLACKOUT_DAYS,
    ):
        self.max_theta = max_theta
        self.max_delta = max_delta
        self.max_vega = max_vega
        self.max_positions = max_positions
        self.earnings_blackout_days = earnings_blackout_days

    def check_new_position(
        self,
        symbol: str,
        new_theta: float,
        new_delta: float,
        new_vega: float,
        current_theta: float = 0.0,
        current_delta: float = 0.0,
        current_vega: float = 0.0,
        current_positions: int = 0,
        earnings_date: Optional[date] = None,
    ) -> OptionsRiskCheck:
        """
        Check if a new position is safe to open given current portfolio state.
        """
        # Position count limit
        if current_positions >= self.max_positions:
            return OptionsRiskCheck(False, f"Max positions {self.max_positions} reached")

        # Earnings blackout
        if earnings_date:
            days_to_earnings = (earnings_date - date.today()).days
            if 0 <= days_to_earnings <= self.earnings_blackout_days:
                return OptionsRiskCheck(
                    False,
                    f"Earnings blackout: {symbol} reports in {days_to_earnings} days",
                )

        # Greeks limits
        if abs(current_theta + new_theta) > self.max_theta:
            return OptionsRiskCheck(
                False,
                f"Theta limit: {current_theta + new_theta:.0f} > {self.max_theta}",
            )

        if abs(current_delta + new_delta) > self.max_delta:
            return OptionsRiskCheck(
                False,
                f"Delta limit: {abs(current_delta + new_delta):.0f} > {self.max_delta}",
            )

        if abs(current_vega + new_vega) > self.max_vega:
            return OptionsRiskCheck(
                False,
                f"Vega limit: {abs(current_vega + new_vega):.0f} > {self.max_vega}",
            )

        return OptionsRiskCheck(True, "All risk checks passed")
