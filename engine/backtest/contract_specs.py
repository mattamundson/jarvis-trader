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
    "MES": ContractSpec(multiplier=5.0,  tick_size=0.25, commission=0.62, slippage_ticks=1),
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
    # ETFs (no futures multiplier; commission tier varies by broker — assume 0 for IB tiered commissions)
    "SPY": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
    "QQQ": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
    "IWM": ContractSpec(multiplier=1.0, tick_size=0.01, commission=0.00, slippage_ticks=1),
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
