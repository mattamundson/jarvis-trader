"""
JARVIS TRADER — Position Sizer with Pyramiding
Signal-strength scaling and pyramid schedule for micro futures.
Inspired by autotrade's scale-in pattern (30/30/30 on confirmation).

Safety: All sizing passes through SafetyLayer — 2 contract max enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PyramidLevel:
    """A single pyramid entry level."""

    trigger: str  # "initial", "confirmation", "strong_trend"
    contracts: int
    signal_threshold: float  # minimum signal strength [0, 1] to trigger


@dataclass
class PositionSizeResult:
    """Result of position sizing calculation."""

    initial_contracts: int
    pyramid_schedule: List[PyramidLevel] = field(default_factory=list)
    max_total_contracts: int = 2


class PositionSizer:
    """
    ATR-based position sizing with optional pyramiding for micro futures.

    For micro futures with max 2 contracts per instrument:
    - Level 1: Enter 1 contract on initial signal (LEAN_BULL + regime aligned)
    - Level 2: Add 1 contract on confirmation (STRONG_BULL + trend strengthening)
    """

    def __init__(
        self,
        capital: float,
        risk_pct: float = 0.01,
        max_contracts: int = 2,
        enable_pyramiding: bool = True,
    ) -> None:
        self.capital = capital
        self.risk_pct = risk_pct
        self.max_contracts = max_contracts
        self.enable_pyramiding = enable_pyramiding

    def compute_initial_size(
        self, atr: float, stop_mult: float, multiplier: float
    ) -> int:
        """
        ATR-based sizing: risk = contracts * atr * stop_mult * multiplier.
        Returns number of contracts (minimum 1 if entering).
        """
        if atr <= 0 or stop_mult <= 0 or multiplier <= 0:
            return 1

        risk_dollars = self.capital * self.risk_pct
        risk_per_contract = atr * stop_mult * multiplier

        if risk_per_contract <= 0:
            return 1

        raw = risk_dollars / risk_per_contract
        contracts = max(1, min(int(raw), self.max_contracts))

        # If pyramiding is enabled, start with 1 to leave room for adds
        if self.enable_pyramiding and contracts > 1:
            contracts = 1

        return contracts

    def compute_pyramid_schedule(
        self, signal_strength: float
    ) -> List[PyramidLevel]:
        """
        Build pyramid schedule based on signal strength.

        signal_strength: [0, 1] — normalized confidence from Layer 4.
        Returns list of pyramid levels including initial entry.
        """
        if not self.enable_pyramiding or self.max_contracts <= 1:
            return [
                PyramidLevel(
                    trigger="initial",
                    contracts=1,
                    signal_threshold=0.0,
                )
            ]

        schedule = [
            PyramidLevel(
                trigger="initial",
                contracts=1,
                signal_threshold=0.0,
            ),
        ]

        # Only add pyramid level if strong enough signal
        if signal_strength >= 0.7:
            schedule.append(
                PyramidLevel(
                    trigger="confirmation",
                    contracts=1,
                    signal_threshold=0.7,
                )
            )

        return schedule

    def signal_strength_scaling(
        self, base_contracts: int, strength: float
    ) -> int:
        """
        Scale position based on signal strength [0, 1].

        Strength 0.0 → 50% of base (minimum 1)
        Strength 0.5 → 100% of base
        Strength 1.0 → 150% of base (capped at max_contracts)
        """
        scale = 0.5 + strength
        scaled = max(1, int(base_contracts * scale))
        return min(scaled, self.max_contracts)

    def should_pyramid(
        self,
        current_contracts: int,
        signal_strength: float,
        unrealized_pnl: float,
    ) -> Optional[int]:
        """
        Determine if we should add to the position.

        Rules:
        - Only pyramid if currently profitable (unrealized_pnl > 0)
        - Only pyramid if signal strength >= 0.7
        - Never exceed max_contracts
        - Returns number of contracts to add, or None if no pyramid.
        """
        if not self.enable_pyramiding:
            return None

        if current_contracts >= self.max_contracts:
            return None

        if unrealized_pnl <= 0:
            return None

        if signal_strength < 0.7:
            return None

        add = min(1, self.max_contracts - current_contracts)
        return add if add > 0 else None

    def should_scale_out(
        self,
        current_contracts: int,
        signal_strength: float,
    ) -> Optional[int]:
        """
        Determine if we should reduce position size.

        Rules:
        - Scale out 1 contract when signal weakens below 0.3
        - Never scale below 1 contract (full exit handled elsewhere)
        - Returns number of contracts to close, or None.
        """
        if current_contracts <= 1:
            return None

        if signal_strength < 0.3:
            return 1

        return None
