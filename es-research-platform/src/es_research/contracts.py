"""Domain data contracts for Phase 1 of the ES research platform."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AggressorSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class SimulationLevel(StrEnum):
    SCREENING = "screening"
    BAR = "bar"
    EVENT = "event"


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RollRule(StrEnum):
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    DATE = "date"


class AdjustmentMethod(StrEnum):
    NONE = "none"
    BACK_ADJUSTED = "back_adjusted"
    RATIO = "ratio"


class ContractModel(BaseModel):
    """Base model that serializes Decimal and datetime values consistently."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_enum_values=False,
    )


def require_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamps must be timezone-aware; naive datetimes are rejected"
        raise ValueError(msg)
    return value.astimezone(UTC)


def require_non_negative_decimal(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        msg = "value must be non-negative"
        raise ValueError(msg)
    return value


def require_positive_decimal(value: Decimal) -> Decimal:
    if value <= Decimal("0"):
        msg = "value must be positive"
        raise ValueError(msg)
    return value


def require_unit_interval(value: Decimal) -> Decimal:
    if value < Decimal("0") or value > Decimal("1"):
        msg = "value must be between 0 and 1 inclusive"
        raise ValueError(msg)
    return value


class TradeEvent(ContractModel):
    event_timestamp: datetime
    receive_timestamp: datetime | None = None
    instrument_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    aggressor_side: AggressorSide
    sequence_number: int
    venue: str

    _event_timestamp_utc = field_validator("event_timestamp")(require_utc)
    _receive_timestamp_utc = field_validator("receive_timestamp")(
        lambda v: None if v is None else require_utc(v)
    )
    _price_non_negative = field_validator("price")(require_non_negative_decimal)
    _quantity_non_negative = field_validator("quantity")(require_non_negative_decimal)


class BookSnapshot(ContractModel):
    event_timestamp: datetime
    instrument_id: str
    symbol: str
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    sequence_number: int
    venue: str

    _event_timestamp_utc = field_validator("event_timestamp")(require_utc)
    _money = field_validator("bid_price", "bid_quantity", "ask_price", "ask_quantity")(
        require_non_negative_decimal
    )

    @model_validator(mode="after")
    def validate_market(self) -> BookSnapshot:
        if self.ask_price < self.bid_price:
            msg = "ask_price must be greater than or equal to bid_price"
            raise ValueError(msg)
        return self


class InstrumentDefinition(ContractModel):
    instrument_id: str
    raw_symbol: str
    root_symbol: str
    expiration: date
    contract_multiplier: Decimal
    minimum_tick: Decimal
    tick_value: Decimal
    currency: str

    _positive = field_validator("contract_multiplier", "minimum_tick", "tick_value")(
        require_positive_decimal
    )


class SessionCalendar(ContractModel):
    session_id: str
    trade_date: date
    session_open: datetime
    session_close: datetime
    regular_trading_hours_open: datetime
    regular_trading_hours_close: datetime
    timezone: str
    holiday_name: str | None = None

    _timestamps = field_validator(
        "session_open", "session_close", "regular_trading_hours_open", "regular_trading_hours_close"
    )(require_utc)

    @model_validator(mode="after")
    def validate_boundaries(self) -> SessionCalendar:
        if self.session_close <= self.session_open:
            raise ValueError("session_close must be after session_open")
        if self.regular_trading_hours_close <= self.regular_trading_hours_open:
            raise ValueError("regular_trading_hours_close must be after regular_trading_hours_open")
        if not (
            self.session_open
            <= self.regular_trading_hours_open
            < self.regular_trading_hours_close
            <= self.session_close
        ):
            raise ValueError("regular trading hours must be contained within the session")
        return self


class ContractRoll(ContractModel):
    outgoing_contract: str
    incoming_contract: str
    roll_timestamp: datetime
    roll_rule: RollRule
    adjustment_method: AdjustmentMethod
    adjustment_value: Decimal

    _roll_timestamp_utc = field_validator("roll_timestamp")(require_utc)


class FeatureValue(ContractModel):
    name: str
    value: int | float | str | bool | None


class FeatureRow(ContractModel):
    instrument_id: str
    timestamp: datetime
    timeframe: str
    feature_version: str
    values: tuple[FeatureValue, ...]

    _timestamp_utc = field_validator("timestamp")(require_utc)


class StrategyCandidate(ContractModel):
    candidate_id: str
    canonical_strategy_definition: dict[str, Any]
    strategy_hash: str
    parameter_values: dict[str, int | float | str | bool]
    feature_version: str
    creation_timestamp: datetime

    _creation_timestamp_utc = field_validator("creation_timestamp")(require_utc)


class ExperimentRun(ContractModel):
    experiment_id: str
    strategy_hash: str
    data_manifest_hash: str
    feature_version: str
    code_commit: str
    configuration_hash: str
    cost_model_version: str
    simulation_level: SimulationLevel
    start_timestamp: datetime
    end_timestamp: datetime | None = None
    random_seed: int
    status: ExperimentStatus

    _start_timestamp_utc = field_validator("start_timestamp")(require_utc)
    _end_timestamp_utc = field_validator("end_timestamp")(
        lambda v: None if v is None else require_utc(v)
    )


class SimulationResult(ContractModel):
    experiment_id: str
    candidate_id: str
    gross_pnl: Decimal
    net_pnl: Decimal
    trade_count: int = Field(ge=0)
    turnover: Decimal
    maximum_drawdown: Decimal
    sharpe_ratio: Decimal
    win_rate: Decimal
    average_trade: Decimal
    result_timestamp: datetime

    _non_negative = field_validator("turnover", "maximum_drawdown")(require_non_negative_decimal)
    _win_rate_interval = field_validator("win_rate")(require_unit_interval)
    _result_timestamp_utc = field_validator("result_timestamp")(require_utc)
