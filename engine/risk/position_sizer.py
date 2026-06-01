"""
Position Sizing Calculator — determines optimal contract count
based on equity, risk tolerance, ATR, and hard safety limits.

Phase 3 prep: currently paper trading at 1 contract.
This module provides the math for graduated scaling.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Position sizing result."""

    contracts: int
    risk_amount: float  # dollar risk for this position
    max_loss: float  # worst case loss
    sizing_method: str  # "fixed_fractional", "kelly", "atr_based"
    scale_factor: float  # 1.0 = full size, 0.5 = half (drawdown scaling)


def calculate_position_size(
    equity: float,
    risk_pct: float,  # e.g., 1.0 for 1%
    atr: float,
    contract_multiplier: float,  # e.g., 5.0 for MES, 100.0 for MCL, 2.0 for MNQ, 10.0 for MGC
    max_contracts: int = 2,
    max_position_pct: float = 5.0,
    drawdown_pct: float = 0.0,
) -> PositionSize:
    """
    Calculate position size using ATR-based risk.

    Args:
        equity: Current account equity
        risk_pct: Risk per trade as % of equity (e.g., 1.0)
        atr: Average True Range (points)
        contract_multiplier: $/point multiplier — MES=5.0, MNQ=2.0, MCL=100.0, MGC=10.0
                             (authoritative table: utils/position_sizing.py INSTRUMENT_MULTIPLIERS)
        max_contracts: Hard limit on contracts (e.g., 2)
        max_position_pct: Max position value as % of equity (e.g., 5.0)
        drawdown_pct: Current drawdown from peak (e.g., 5.5)

    Returns:
        PositionSize with contracts, risk_amount, max_loss, sizing_method, scale_factor
    """
    # Edge cases
    if equity <= 0 or atr <= 0 or risk_pct <= 0:
        return PositionSize(
            contracts=0,
            risk_amount=0.0,
            max_loss=0.0,
            sizing_method="atr_based",
            scale_factor=1.0,
        )

    # Apply drawdown scaling
    scale = drawdown_scale_factor(drawdown_pct)
    effective_risk_pct = risk_pct * scale

    # Risk budget for this trade
    risk_budget = (equity * effective_risk_pct) / 100.0

    # Risk per contract (ATR in dollars)
    risk_per_contract = atr * contract_multiplier

    if risk_per_contract <= 0:
        return PositionSize(
            contracts=0,
            risk_amount=0.0,
            max_loss=0.0,
            sizing_method="atr_based",
            scale_factor=scale,
        )

    # Calculate contracts based on risk budget
    contracts_from_risk = int(risk_budget / risk_per_contract)

    # Apply hard limits
    contracts = min(contracts_from_risk, max_contracts)

    # Position value check (contracts * ATR * multiplier should not exceed max_position_pct of equity)
    if contracts > 0:
        position_value = contracts * atr * contract_multiplier
        max_position_value = (equity * max_position_pct) / 100.0

        while contracts > 0 and position_value > max_position_value:
            contracts -= 1
            position_value = contracts * atr * contract_multiplier if contracts > 0 else 0

    # Calculate actual risk amount and max loss
    if contracts > 0:
        risk_amount = contracts * atr * contract_multiplier
        max_loss = risk_amount
    else:
        risk_amount = 0.0
        max_loss = 0.0

    return PositionSize(
        contracts=contracts,
        risk_amount=risk_amount,
        max_loss=max_loss,
        sizing_method="atr_based",
        scale_factor=scale,
    )


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Kelly criterion for optimal bet sizing.

    Formula: f* = (bp - q) / b
      where b = avg_win/avg_loss, p = win_rate, q = 1-win_rate

    Returns fraction of equity to risk (0.0 to 1.0).
    Capped at 0.25 for safety (quarter-Kelly).

    Args:
        win_rate: Win rate as decimal (e.g., 0.55 for 55%)
        avg_win: Average win size
        avg_loss: Average loss size (positive value)

    Returns:
        Fraction of equity to risk (0.0 to 0.25)
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0

    if win_rate <= 0 or win_rate >= 1:
        return 0.0

    p = win_rate
    q = 1 - p
    b = avg_win / avg_loss

    # Kelly formula
    kelly = (b * p - q) / b if b > 0 else 0.0

    # Clamp to [0, 0.25] for safety (quarter-Kelly)
    kelly = max(0.0, min(kelly, 0.25))

    return kelly


def drawdown_scale_factor(current_drawdown_pct: float) -> float:
    """
    Risk scaling ladder based on current drawdown from peak.

    Scaling tiers:
      0-5% DD:   1.0x (full size)
      5-8% DD:   0.75x
      8-10% DD:  0.5x
      10%+ DD:   0.0x (stop trading — kill switch territory)

    Args:
        current_drawdown_pct: Drawdown from peak as % (e.g., 5.5)

    Returns:
        Scale factor (1.0 to 0.0)
    """
    if current_drawdown_pct < 0:
        return 1.0

    if current_drawdown_pct < 5:
        return 1.0
    elif current_drawdown_pct < 8:
        return 0.75
    elif current_drawdown_pct < 10:
        return 0.5
    else:
        return 0.0
