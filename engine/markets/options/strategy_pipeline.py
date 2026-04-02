"""
OptionsStrategyPipeline — selects and sizes options strategies based on VIX regime.

Regime → Strategy mapping:
  low_vix (VIX < 15)    → Iron Condors (sell wide strangle, buy wings)
  normal (15-25)        → Credit Spreads (bull put / bear call)
  high_vix (VIX > 25)  → Reduced size or cash (skip high-IV uncertainty)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .scanner import ScanResult

logger = logging.getLogger("jarvis_trader.markets.options.strategy")


@dataclass
class OptionsTradeSpec:
    """Specification for an options trade to be executed."""
    strategy: str  # "iron_condor" | "bull_put_spread" | "bear_call_spread"
    symbol: str
    expiry: str
    # Legs: (strike, right, action, qty) — right = "C" | "P"
    legs: list[tuple[float, str, str, int]]
    max_loss: float
    credit_target: float
    reason: str


class OptionsStrategyPipeline:
    """
    Takes scan results and produces trade specifications.
    Uses VIX regime to select appropriate premium-selling strategy.
    """

    def __init__(self, max_position_capital: float = 5000.0, contracts_per_trade: int = 1):
        self.max_position_capital = max_position_capital
        self.contracts_per_trade = contracts_per_trade

    def generate(self, scan_results: list[ScanResult]) -> list[OptionsTradeSpec]:
        """Convert scan results into actionable trade specs."""
        specs = []
        for result in scan_results:
            try:
                spec = self._build_spec(result)
                if spec:
                    specs.append(spec)
            except Exception as exc:
                logger.error(f"Strategy pipeline error for {result.symbol}: {exc}")
        return specs

    def _build_spec(self, result: ScanResult) -> Optional[OptionsTradeSpec]:
        """Build trade spec for one scan result."""
        if result.regime == "high_vix":
            logger.info(f"{result.symbol}: high VIX regime — skipping new positions")
            return None

        qty = self.contracts_per_trade

        if result.regime == "low_vix":
            # Iron Condor: sell OTM put + call, buy further OTM for protection
            legs = [
                (result.put_strikes[0], "P", "sell", qty),   # short put
                (result.put_strikes[1], "P", "buy", qty),    # long put (wing)
                (result.call_strikes[0], "C", "sell", qty),  # short call
                (result.call_strikes[1], "C", "buy", qty),   # long call (wing)
            ]
            spread_width = result.put_strikes[0] - result.put_strikes[1]
            max_loss = spread_width * qty * 100
            credit_target = max_loss * 0.33  # Target 1/3 of width as credit

            return OptionsTradeSpec(
                strategy="iron_condor",
                symbol=result.symbol,
                expiry=result.expiry,
                legs=legs,
                max_loss=max_loss,
                credit_target=credit_target,
                reason=f"IV Rank {result.iv_rank:.0f}, low VIX regime, {result.days_to_expiry} DTE",
            )

        else:  # normal regime
            # Bull Put Spread (most common in neutral/mildly bullish)
            legs = [
                (result.put_strikes[0], "P", "sell", qty),  # short put
                (result.put_strikes[1], "P", "buy", qty),   # long put (protection)
            ]
            spread_width = result.put_strikes[0] - result.put_strikes[1]
            max_loss = spread_width * qty * 100
            credit_target = max_loss * 0.30

            return OptionsTradeSpec(
                strategy="bull_put_spread",
                symbol=result.symbol,
                expiry=result.expiry,
                legs=legs,
                max_loss=max_loss,
                credit_target=credit_target,
                reason=f"IV Rank {result.iv_rank:.0f}, normal VIX, {result.days_to_expiry} DTE",
            )
