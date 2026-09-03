"""B-01 Instrument Master contract and legacy-metadata seed.

The registry is not wired into active sizing, P&L, market-data, or broker code.
It deliberately refuses ambiguous legacy aliases instead of silently inheriting
provider-specific symbol semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class AssetClass(str, Enum):
    FUTURE = "FUTURE"
    EQUITY = "EQUITY"
    CRYPTO = "CRYPTO"


class UnknownInstrumentError(KeyError):
    """Raised when Instrument Master cannot resolve a canonical instrument."""


class AmbiguousInstrumentAliasError(ValueError):
    """Raised when a legacy/provider alias requires explicit disposition."""


@dataclass(frozen=True)
class InstrumentSpec:
    root: str
    asset_class: AssetClass
    point_value_usd: float
    quote_currency: str = "USD"
    source: str = "legacy:engine/utils/position_sizing.py"
    version: int = 1

    def __post_init__(self) -> None:
        root = self.root.strip().upper()
        if not root:
            raise ValueError("root is required")
        if self.point_value_usd <= 0:
            raise ValueError("point_value_usd must be positive")
        if self.quote_currency != "USD":
            raise ValueError("v1 seed supports USD quote currency only")
        object.__setattr__(self, "root", root)


# Canonical-root seed copies only explicit root multipliers already present in
# the legacy position-sizing table. This is metadata migration evidence, not
# execution authorization and not a statement that each instrument is enabled.
_SEED: dict[str, InstrumentSpec] = {
    "MES": InstrumentSpec("MES", AssetClass.FUTURE, 5.0),
    "MNQ": InstrumentSpec("MNQ", AssetClass.FUTURE, 2.0),
    "MCL": InstrumentSpec("MCL", AssetClass.FUTURE, 100.0),
    "MGC": InstrumentSpec("MGC", AssetClass.FUTURE, 10.0),
    "MHG": InstrumentSpec("MHG", AssetClass.FUTURE, 2500.0),
    "M2K": InstrumentSpec("M2K", AssetClass.FUTURE, 5.0),
    "MSI": InstrumentSpec("MSI", AssetClass.FUTURE, 1000.0),
    "ES": InstrumentSpec("ES", AssetClass.FUTURE, 50.0),
    "NQ": InstrumentSpec("NQ", AssetClass.FUTURE, 20.0),
    "SPY": InstrumentSpec("SPY", AssetClass.EQUITY, 1.0),
    "QQQ": InstrumentSpec("QQQ", AssetClass.EQUITY, 1.0),
    "AAPL": InstrumentSpec("AAPL", AssetClass.EQUITY, 1.0),
    "TSLA": InstrumentSpec("TSLA", AssetClass.EQUITY, 1.0),
}

# These names exist in the legacy multiplier table but are provider/continuous
# symbols rather than canonical roots. B-01 must explicitly map their contract
# semantics before any new authority is allowed to resolve them automatically.
LEGACY_ALIASES_REQUIRING_DISPOSITION = frozenset({"MES=F", "NQ=F", "CL=F", "GC=F"})


class InstrumentRegistry:
    """Read-only v1 registry; authorization is intentionally out of scope."""

    def __init__(self, specs: Mapping[str, InstrumentSpec] | None = None) -> None:
        source = dict(specs or _SEED)
        normalized: dict[str, InstrumentSpec] = {}
        for key, spec in source.items():
            root = key.strip().upper()
            if root != spec.root:
                raise ValueError(f"registry key {root!r} must equal spec.root {spec.root!r}")
            if root in normalized:
                raise ValueError(f"duplicate instrument root: {root}")
            normalized[root] = spec
        self._specs = MappingProxyType(normalized)

    @property
    def specs(self) -> Mapping[str, InstrumentSpec]:
        return self._specs

    def resolve(self, symbol: str) -> InstrumentSpec:
        normalized = symbol.strip().upper()
        if normalized in LEGACY_ALIASES_REQUIRING_DISPOSITION:
            raise AmbiguousInstrumentAliasError(
                f"legacy alias {normalized!r} requires explicit B-01 mapping disposition"
            )
        try:
            return self._specs[normalized]
        except KeyError as exc:
            raise UnknownInstrumentError(normalized) from exc

    def contains(self, symbol: str) -> bool:
        try:
            self.resolve(symbol)
        except (UnknownInstrumentError, AmbiguousInstrumentAliasError):
            return False
        return True

    def roots(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


DEFAULT_INSTRUMENT_REGISTRY = InstrumentRegistry()
