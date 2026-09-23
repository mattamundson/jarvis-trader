"""Canonical contract specifications for backtests and cost modeling.

This module is the single source of truth for per-symbol contract properties:
multiplier, tick size, commission, and typical slippage. Previously these
values were duplicated across `scripts/mes_trend_search.py`, `scripts/
mcl_meanrev_search.py`, `scripts/multi_symbol_trend_wfo.py`, and
`backtest/data_loader.py::CONTRACT_MULTIPLIERS`, which drifted — notably
MCL commission was 0.62 in one script and 0.85 in another.

**Commission canonicalization**: Values reflect IB actual round-trip tier 1
pricing (per contract per leg) as of 2026-04. MCL (micro crude) is priced
higher than equity micros (MES/MNQ) because CME and NYMEX fee schedules
differ. When IB rates change, update this module — all consumers import
from here.

**Slippage**: Typical slippage observed on 1h bars in current cache. MNQ is
2 ticks not 1 because Nasdaq futures gap through stops more often than ES
micros. This is an empirical observation from live paper-trade logs, not a
uniform assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ContractSpec:
    """Per-symbol contract specification."""

    multiplier: float       # USD per point of price movement
    tick_size: float        # minimum price increment
    commission: float       # per contract per leg (IB tier 1 baseline)
    slippage_ticks: int     # typical 1h-bar slippage in ticks

    @property
    def tick_value(self) -> float:
        """Dollar value of a single tick: multiplier * tick_size."""
        return self.multiplier * self.tick_size

    @property
    def round_trip_commission(self) -> float:
        """Round-trip commission (both legs)."""
        return 2.0 * self.commission


CONTRACT_SPECS: Dict[str, ContractSpec] = {
    # Equity index micros
<<<<<<< HEAD
    "MES": ContractSpec(multiplier=5.0,  tick_size=0.25, commission=0.62, slippage_ticks=1),
=======
    "MES": ContractSpec(multiplier=5.0, tick_size=0.25, commission=0.71, slippage_ticks=1),
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    "MNQ": ContractSpec(multiplier=2.0,  tick_size=0.25, commission=0.62, slippage_ticks=2),
    "M2K": ContractSpec(multiplier=5.0,  tick_size=0.10, commission=0.62, slippage_ticks=1),
    "MYM": ContractSpec(multiplier=0.5,  tick_size=1.00, commission=0.62, slippage_ticks=1),
    # Equity index full-size
    "ES":  ContractSpec(multiplier=50.0, tick_size=0.25, commission=1.38, slippage_ticks=1),
    "NQ":  ContractSpec(multiplier=20.0, tick_size=0.25, commission=1.38, slippage_ticks=1),
    "RTY": ContractSpec(multiplier=50.0, tick_size=0.10, commission=1.38, slippage_ticks=1),
    "YM":  ContractSpec(multiplier=5.0,  tick_size=1.00, commission=1.38, slippage_ticks=1),
    # Energy
    "MCL": ContractSpec(multiplier=100.0,  tick_size=0.01, commission=0.85, slippage_ticks=1),
    "CL":  ContractSpec(multiplier=1000.0, tick_size=0.01, commission=1.49, slippage_ticks=1),
    # Metals
    "MGC": ContractSpec(multiplier=10.0,  tick_size=0.10, commission=0.85, slippage_ticks=1),
    "GC":  ContractSpec(multiplier=100.0, tick_size=0.10, commission=1.49, slippage_ticks=1),
    # Rates (CBOT Treasury futures) -- B1 trend diversifiers, gold-uncorrelated.
    # Full-size, liquid, clean trending price series. tick_size is the decimal
    # form of the fractional minimum tick (ZN = 1/64 = 0.015625, ZB = 1/32 =
    # 0.03125). [ASSUMPTION] commission is an IB tiered-rate estimate pending
    # live-fill confirmation; the cost sweep stresses 0.5x..4x so the gate verdict
    # is robust to this value. If the edge validates, the micro-yield products
    # (10Y/30Y) are the small-account-tradeable equivalents.
    "ZN":  ContractSpec(multiplier=1000.0, tick_size=0.015625, commission=1.20, slippage_ticks=1),
    "ZB":  ContractSpec(multiplier=1000.0, tick_size=0.03125,  commission=1.20, slippage_ticks=1),
    # FX micros (CME Micro FX) -- B1 trend diversifiers, gold-uncorrelated.
    # M6E = 1/10 of 6E (EUR12,500); M6B = 1/10 of 6B (GBP6,250). Priced USD per
    # unit, tick 0.0001. [ASSUMPTION] commission is an IB micro-FX estimate
    # pending live-fill confirmation; cost sweep stresses it.
    "M6E": ContractSpec(multiplier=12500.0, tick_size=0.0001, commission=0.25, slippage_ticks=1),
    "M6B": ContractSpec(multiplier=6250.0,  tick_size=0.0001, commission=0.25, slippage_ticks=1),
    # ETFs (no futures multiplier; commission tier varies by broker — assume 0 for IB tiered commissions)
    "SPY": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
    "QQQ": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
    "IWM": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
    # Cash-settled index OPTIONS underlyings (SPX / VIX exposure via options vehicle).
    # multiplier is the index-option contract multiplier ($100/index-point), tick_size
    # is the option premium increment. commission is IB per-contract for index options.
    # [ASSUMPTION] commission ($0.65/contract) is an IB tiered estimate; the backtest
    # cost sweep (0.5x..4x) keeps gate verdicts robust to it.
    #
    # SPX  : full S&P 500 index options, cash-settled, European-style.
    # XSP  : Mini-SPX index options = 1/10 of SPX level, same $100 multiplier.
    # VIX  : VIX index is NOT directly tradeable — this spec is for VIX *options*.
    #        Direct vol exposure uses the VX / VXM futures below.
    "SPX": ContractSpec(multiplier=100.0, tick_size=0.05, commission=0.65, slippage_ticks=1),
    "XSP": ContractSpec(multiplier=100.0, tick_size=0.01, commission=0.65, slippage_ticks=1),
    "VIX": ContractSpec(multiplier=100.0, tick_size=0.05, commission=0.65, slippage_ticks=1),
    # Volatility FUTURES (CFE). VX = standard VIX future ($1,000/pt), VXM = Micro VIX
    # future ($100/pt). slippage is wider than equity micros — VX gaps through stops
    # around vol spikes. [ASSUMPTION] commissions are IB CFE estimates pending live fills;
    # cost sweep stresses them. These products carry roll/contango cost the trend cost
    # model does NOT yet capture — flag before any forward-test promotion.
    "VX":  ContractSpec(multiplier=1000.0, tick_size=0.05, commission=1.50, slippage_ticks=2),
    "VXM": ContractSpec(multiplier=100.0,  tick_size=0.05, commission=0.37, slippage_ticks=1),
}


def get_spec(symbol: str) -> ContractSpec:
    """Return ContractSpec for symbol. Raises KeyError if unknown."""
    sym = symbol.upper()
    if sym not in CONTRACT_SPECS:
        raise KeyError(f"No contract spec registered for {sym!r}. Add it to CONTRACT_SPECS in contract_specs.py.")
    return CONTRACT_SPECS[sym]


# Backward-compatibility view for legacy CONTRACT_MULTIPLIERS consumers.
# New code should import CONTRACT_SPECS directly.
CONTRACT_MULTIPLIERS: Dict[str, float] = {sym: spec.multiplier for sym, spec in CONTRACT_SPECS.items()}
