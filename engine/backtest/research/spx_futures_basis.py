"""Pure SPX cash-strike to ES/MES futures-level basis translator.

Research utility only. It does not fetch market data or connect to a broker.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Literal

FuturesSymbol = Literal["ES", "MES"]


@dataclass(frozen=True)
class BasisTranslationInput:
    spx_strike: float
    spx_spot: float
    risk_free_rate: float
    dividend_yield: float
    valuation_time: datetime
    spot_timestamp: datetime
    contract_symbol: str
    contract_expiry: date
    output_symbol: FuturesSymbol = "ES"
    observed_futures_price: float | None = None
    observed_futures_timestamp: datetime | None = None
    max_age_seconds: float = 60.0
    max_clock_skew_seconds: float = 10.0
    roll_window_days: int = 8
    tick_size: float = 0.25


@dataclass(frozen=True)
class BasisTranslationResult:
    original_spx_strike: float
    spx_spot: float
    output_symbol: str
    contract_symbol: str
    contract_expiry: str
    valuation_time: str
    year_fraction: float
    theoretical_futures_price_at_spot: float
    theoretical_basis: float
    observed_basis: float | None
    selected_basis: float
    basis_source: str
    translated_unrounded: float
    translated_level: float
    spot_age_seconds: float
    futures_age_seconds: float | None
    input_clock_skew_seconds: float | None
    days_to_expiry: float
    in_roll_window: bool
    stale_observed_basis_rejected: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _round_to_tick(value: float, tick_size: float) -> float:
    return round(round(value / tick_size) * tick_size, 10)


def translate_spx_strike(inputs: BasisTranslationInput) -> BasisTranslationResult:
    if inputs.output_symbol not in {"ES", "MES"}:
        raise ValueError("output_symbol must be ES or MES")
    if inputs.spx_strike <= 0 or inputs.spx_spot <= 0:
        raise ValueError("SPX strike and spot must be positive")
    if inputs.tick_size <= 0:
        raise ValueError("tick_size must be positive")
    valuation = _aware_utc(inputs.valuation_time, "valuation_time")
    spot_ts = _aware_utc(inputs.spot_timestamp, "spot_timestamp")
    expiry_dt = datetime.combine(inputs.contract_expiry, datetime.min.time(), tzinfo=timezone.utc)
    seconds_to_expiry = (expiry_dt - valuation).total_seconds()
    if seconds_to_expiry <= 0:
        raise ValueError("futures contract is expired")
    year_fraction = seconds_to_expiry / (365.25 * 86400.0)
    spot_age = (valuation - spot_ts).total_seconds()
    if spot_age < -inputs.max_clock_skew_seconds:
        raise ValueError("spot timestamp is materially in the future")
    if spot_age > inputs.max_age_seconds:
        raise ValueError("SPX spot is stale; translation fails closed")

    carry_factor = math.exp((inputs.risk_free_rate - inputs.dividend_yield) * year_fraction)
    theoretical_futures = inputs.spx_spot * carry_factor
    theoretical_basis = theoretical_futures - inputs.spx_spot
    selected_basis = theoretical_basis
    basis_source = "theoretical_carry"
    observed_basis = None
    futures_age = None
    skew = None
    stale_rejected = False

    has_price = inputs.observed_futures_price is not None
    has_ts = inputs.observed_futures_timestamp is not None
    if has_price != has_ts:
        raise ValueError("observed futures price and timestamp must be supplied together")
    if has_price and has_ts:
        if float(inputs.observed_futures_price) <= 0:
            raise ValueError("observed futures price must be positive")
        futures_ts = _aware_utc(inputs.observed_futures_timestamp, "observed_futures_timestamp")
        futures_age = (valuation - futures_ts).total_seconds()
        skew = abs((futures_ts - spot_ts).total_seconds())
        observed_fresh = (
            -inputs.max_clock_skew_seconds <= futures_age <= inputs.max_age_seconds
            and skew <= inputs.max_clock_skew_seconds
        )
        observed_basis = float(inputs.observed_futures_price) - inputs.spx_spot
        if observed_fresh:
            selected_basis = observed_basis
            basis_source = "observed_synchronized_basis"
        else:
            stale_rejected = True

    # A near-spot SPX strike is translated with the contemporaneous additive
    # futures-cash basis. This preserves the original strike in the artifact.
    translated_unrounded = inputs.spx_strike + selected_basis
    translated = _round_to_tick(translated_unrounded, inputs.tick_size)
    days_to_expiry = seconds_to_expiry / 86400.0
    return BasisTranslationResult(
        original_spx_strike=inputs.spx_strike,
        spx_spot=inputs.spx_spot,
        output_symbol=inputs.output_symbol,
        contract_symbol=inputs.contract_symbol,
        contract_expiry=inputs.contract_expiry.isoformat(),
        valuation_time=valuation.isoformat(),
        year_fraction=round(year_fraction, 12),
        theoretical_futures_price_at_spot=round(theoretical_futures, 8),
        theoretical_basis=round(theoretical_basis, 8),
        observed_basis=round(observed_basis, 8) if observed_basis is not None else None,
        selected_basis=round(selected_basis, 8),
        basis_source=basis_source,
        translated_unrounded=round(translated_unrounded, 8),
        translated_level=translated,
        spot_age_seconds=round(spot_age, 6),
        futures_age_seconds=round(futures_age, 6) if futures_age is not None else None,
        input_clock_skew_seconds=round(skew, 6) if skew is not None else None,
        days_to_expiry=round(days_to_expiry, 6),
        in_roll_window=days_to_expiry <= inputs.roll_window_days,
        stale_observed_basis_rejected=stale_rejected,
    )
