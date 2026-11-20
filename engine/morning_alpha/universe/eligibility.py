from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.config import MorningAlphaConfig


class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    PRICE_TOO_LOW = "price_too_low"
    ADV_TOO_LOW = "adv_too_low"
    DOLLAR_VOLUME_TOO_LOW = "dollar_volume_too_low"
    LEVERAGED_ETF = "leveraged_etf"
    STALE = "stale"
    FUTURE_DATA = "future_data"
    NOT_ACTIVE_AS_OF = "not_active_as_of"


class UniverseRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    price: float = Field(gt=0)
    avg_daily_shares_20d: float = Field(ge=0)
    avg_dollar_volume_20d: float = Field(ge=0)
    is_leveraged_etf: bool = False
    effective_from: datetime
    effective_to: datetime | None = None
    market_timestamp: datetime

    @model_validator(mode="after")
    def require_aware_datetimes(self) -> "UniverseRecord":
        for name in ("effective_from", "effective_to", "market_timestamp"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        return self


class EligibilityDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    eligible: bool
    reason: EligibilityReason
    as_of: datetime


def evaluate_eligibility(
    record: UniverseRecord,
    *,
    as_of: datetime,
    config: MorningAlphaConfig,
    max_staleness: timedelta = timedelta(days=1),
) -> EligibilityDecision:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    def reject(reason: EligibilityReason) -> EligibilityDecision:
        return EligibilityDecision(symbol=record.symbol, eligible=False, reason=reason, as_of=as_of)

    if record.market_timestamp > as_of:
        return reject(EligibilityReason.FUTURE_DATA)
    if as_of - record.market_timestamp > max_staleness:
        return reject(EligibilityReason.STALE)
    if as_of < record.effective_from:
        return reject(EligibilityReason.NOT_ACTIVE_AS_OF)
    if record.effective_to is not None and as_of >= record.effective_to:
        return reject(EligibilityReason.NOT_ACTIVE_AS_OF)
    if record.is_leveraged_etf:
        return reject(EligibilityReason.LEVERAGED_ETF)
    if record.price < config.min_price:
        return reject(EligibilityReason.PRICE_TOO_LOW)
    if record.avg_daily_shares_20d < config.min_avg_daily_shares:
        return reject(EligibilityReason.ADV_TOO_LOW)
    if record.avg_dollar_volume_20d < config.min_avg_dollar_volume_20d:
        return reject(EligibilityReason.DOLLAR_VOLUME_TOO_LOW)
    return EligibilityDecision(
        symbol=record.symbol,
        eligible=True,
        reason=EligibilityReason.ELIGIBLE,
        as_of=as_of,
    )
