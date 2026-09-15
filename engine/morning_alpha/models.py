from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class StrategyKey(FrozenModel):
    strategy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @property
    def canonical(self) -> str:
        return f"{self.strategy_id}@{self.version}"


class Session(StrEnum):
    PREMARKET = "premarket"
    RTH = "rth"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


class MarketBar(FrozenModel):
    symbol: str = Field(min_length=1)
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)
    session: Session = Session.RTH
    source: str = Field(min_length=1)
    ingested_at: datetime

    @model_validator(mode="after")
    def validate_bar(self) -> "MarketBar":
        if self.timestamp.tzinfo is None or self.ingested_at.tzinfo is None:
            raise ValueError("market timestamps must be timezone-aware")
        if self.low > self.high:
            raise ValueError("bar low cannot exceed high")
        if not self.low <= min(self.open, self.close) <= self.high:
            raise ValueError("open/close must lie within bar range")
        return self


class InstrumentSnapshot(FrozenModel):
    symbol: str = Field(min_length=1)
    as_of: datetime
    price: float = Field(gt=0)
    previous_close: float | None = Field(default=None, gt=0)
    avg_daily_shares_20d: float | None = Field(default=None, ge=0)
    avg_dollar_volume_20d: float | None = Field(default=None, ge=0)
    high_52w: float | None = Field(default=None, gt=0)
    sector: str | None = None
    source: str = Field(min_length=1)
    ingested_at: datetime
    stale: bool = False


class SectorSnapshot(FrozenModel):
    symbol: str
    sector: str
    as_of: datetime
    returns_1d: float | None = None
    returns_5d: float | None = None
    returns_20d: float | None = None
    returns_50d: float | None = None
    relative_to_spy_20d: float | None = None
    distance_from_52w_high: float | None = None
    volume_acceleration: float | None = None
    source: str


class MarketRegime(FrozenModel):
    as_of: datetime
    spy_trend: str
    qqq_trend: str
    iwm_relative_strength: float | None = None
    vix_bucket: str
    breadth_score: float | None = None
    ten_year_yield_trend: str | None = None
    crude_trend: str | None = None
    scheduled_event_risk: bool = False
    risk_state: str


class CatalystSnapshot(FrozenModel):
    symbol: str
    as_of: datetime
    catalyst_type: str
    headline: str
    source_url: str | None = None
    published_at: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = False


class SetupCandidate(FrozenModel):
    symbol: str
    strategy: StrategyKey
    as_of: datetime
    side: Literal["long", "short"]
    setup_type: str
    thesis_code: str
    proposed_entry: float
    proposed_stop: float
    nearby_obstacle: float | None = None
    sector: str | None = None
    theme: str | None = None
    source: str = "deterministic"


class TradePlan(FrozenModel):
    symbol: str
    strategy: StrategyKey
    as_of: datetime
    side: Literal["long", "short"]
    entry: float
    stop: float
    targets: tuple[float, ...]
    risk_per_share: float = Field(gt=0)
    account_equity: float = Field(gt=0)
    risk_fraction: float
    shares: int = Field(gt=0)
    max_dollar_risk: float = Field(gt=0)
    expected_r: float
    sector: str | None = None
    theme: str | None = None

    @model_validator(mode="after")
    def validate_trade_plan(self) -> "TradePlan":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.risk_fraction <= 0 or self.risk_fraction > 0.01:
            raise ValueError("risk_fraction must be > 0 and <= 0.01")
        if self.expected_r < 2.0:
            raise ValueError("trade plan requires minimum 2.0R expected reward")
        if self.side == "long" and not self.stop < self.entry:
            raise ValueError("long stop must be below entry")
        if self.side == "short" and not self.stop > self.entry:
            raise ValueError("short stop must be above entry")
        calculated = abs(self.entry - self.stop)
        if abs(calculated - self.risk_per_share) > max(1e-9, calculated * 1e-6):
            raise ValueError("risk_per_share must equal absolute entry-stop distance")
        if self.max_dollar_risk > self.account_equity * self.risk_fraction + 1e-6:
            raise ValueError("max_dollar_risk exceeds configured risk_fraction")
        return self


class OutcomeClassification(StrEnum):
    WIN = "win"
    LOSS = "loss"
    OPEN = "open"
    FILTERED_WINNER = "filtered_winner"
    FILTERED_LOSER = "filtered_loser"
    UNVERIFIED = "unverified"


class SignalOutcome(FrozenModel):
    symbol: str
    strategy: StrategyKey
    signal_as_of: datetime
    evaluated_as_of: datetime
    triggered: bool
    classification: OutcomeClassification
    entry_price: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    close_r: float | None = None
    stop_hit: bool | None = None
    reached_1r: bool | None = None
    reached_2r: bool | None = None
    reached_3r: bool | None = None
    reached_4r: bool | None = None
