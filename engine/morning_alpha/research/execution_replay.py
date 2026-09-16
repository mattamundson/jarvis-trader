from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionReplayStatus(StrEnum):
    FILLED = "FILLED"
    PARTIAL_FILL = "PARTIAL_FILL"
    UNVERIFIED_EXECUTION = "UNVERIFIED_EXECUTION"


class ExecutionQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    bid_size: float = Field(ge=0)
    ask_size: float = Field(ge=0)
    last: float | None = Field(default=None, gt=0)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_quote(self) -> "ExecutionQuote":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")
        if self.ask < self.bid:
            raise ValueError("ask must be >= bid")
        return self


class ExecutionIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1)
    side: OrderSide
    quantity: int = Field(gt=0)
    trigger_timestamp: datetime
    reference_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    risk_per_share: float = Field(gt=0)
    max_delay_seconds: int = Field(ge=0)
    max_participation_fraction: float = Field(gt=0, le=1)
    commission_per_share: float = Field(default=0.0, ge=0)
    impact_bps: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_intent(self) -> "ExecutionIntent":
        if self.trigger_timestamp.tzinfo is None or self.trigger_timestamp.utcoffset() is None:
            raise ValueError("trigger_timestamp must be timezone-aware")
        return self


class ExecutionFill(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    quantity: int = Field(gt=0)
    bid: float
    ask: float
    quoted_cross_price: float
    fill_price: float
    source: str


class ExecutionReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    side: OrderSide
    status: ExecutionReplayStatus
    requested_quantity: int
    filled_quantity: int = Field(ge=0)
    unfilled_quantity: int = Field(ge=0)
    fill_ratio: float = Field(ge=0, le=1)
    delay_seconds: int = Field(ge=0)
    average_entry_price: float | None = None
    implementation_shortfall_per_share: float | None = None
    spread_crossing_cost: float = Field(ge=0)
    impact_cost: float = Field(ge=0)
    commission_cost: float = Field(ge=0)
    fills: tuple[ExecutionFill, ...] = ()
    stop_fill_price: float | None = None
    theoretical_stop_r: float | None = None
    realized_r: float | None = None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 12)


def _cross_price(side: OrderSide, quote: ExecutionQuote) -> float:
    return quote.ask if side is OrderSide.BUY else quote.bid


def _displayed_size(side: OrderSide, quote: ExecutionQuote) -> float:
    return quote.ask_size if side is OrderSide.BUY else quote.bid_size


def _impacted_price(side: OrderSide, price: float, impact_bps: float) -> float:
    impact = impact_bps / 10_000.0
    return price * (1.0 + impact) if side is OrderSide.BUY else price * (1.0 - impact)


def _entry_shortfall(side: OrderSide, fill: float, reference: float) -> float:
    return fill - reference if side is OrderSide.BUY else reference - fill


def _stop_side(entry_side: OrderSide) -> OrderSide:
    return OrderSide.SELL if entry_side is OrderSide.BUY else OrderSide.BUY


def _theoretical_stop_r(intent: ExecutionIntent) -> float:
    pnl = (
        intent.stop_price - intent.reference_price
        if intent.side is OrderSide.BUY
        else intent.reference_price - intent.stop_price
    )
    return pnl / intent.risk_per_share


def _realized_r(intent: ExecutionIntent, entry_price: float, exit_price: float) -> float:
    pnl = exit_price - entry_price if intent.side is OrderSide.BUY else entry_price - exit_price
    return pnl / intent.risk_per_share


def replay_execution(
    intent: ExecutionIntent,
    quotes: tuple[ExecutionQuote, ...] | list[ExecutionQuote],
    *,
    delay_seconds: int = 0,
    stop_quotes: tuple[ExecutionQuote, ...] | list[ExecutionQuote] = (),
    stop_trigger_timestamp: datetime | None = None,
) -> ExecutionReplayResult:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be non-negative")
    if delay_seconds > intent.max_delay_seconds:
        return ExecutionReplayResult(
            candidate_id=intent.candidate_id,
            side=intent.side,
            status=ExecutionReplayStatus.UNVERIFIED_EXECUTION,
            requested_quantity=intent.quantity,
            filled_quantity=0,
            unfilled_quantity=intent.quantity,
            fill_ratio=0.0,
            delay_seconds=delay_seconds,
            spread_crossing_cost=0.0,
            impact_cost=0.0,
            commission_cost=0.0,
        )

    target = intent.trigger_timestamp + timedelta(seconds=delay_seconds)
    deadline = intent.trigger_timestamp + timedelta(seconds=intent.max_delay_seconds)
    eligible = sorted(
        (q for q in quotes if target <= q.timestamp <= deadline),
        key=lambda q: q.timestamp,
    )
    if not eligible:
        return ExecutionReplayResult(
            candidate_id=intent.candidate_id,
            side=intent.side,
            status=ExecutionReplayStatus.UNVERIFIED_EXECUTION,
            requested_quantity=intent.quantity,
            filled_quantity=0,
            unfilled_quantity=intent.quantity,
            fill_ratio=0.0,
            delay_seconds=delay_seconds,
            spread_crossing_cost=0.0,
            impact_cost=0.0,
            commission_cost=0.0,
        )

    remaining = intent.quantity
    fills: list[ExecutionFill] = []
    spread_cost = 0.0
    impact_cost = 0.0
    total_notional = 0.0
    total_qty = 0

    for quote in eligible:
        capacity = int(math.floor(_displayed_size(intent.side, quote) * intent.max_participation_fraction))
        if capacity <= 0:
            continue
        qty = min(remaining, capacity)
        quoted = _cross_price(intent.side, quote)
        fill = _impacted_price(intent.side, quoted, intent.impact_bps)
        mid = (quote.bid + quote.ask) / 2.0
        spread_per_share = quoted - mid if intent.side is OrderSide.BUY else mid - quoted
        impact_per_share = fill - quoted if intent.side is OrderSide.BUY else quoted - fill
        spread_cost += max(0.0, spread_per_share) * qty
        impact_cost += max(0.0, impact_per_share) * qty
        total_notional += fill * qty
        total_qty += qty
        fills.append(
            ExecutionFill(
                timestamp=quote.timestamp,
                quantity=qty,
                bid=quote.bid,
                ask=quote.ask,
                quoted_cross_price=quoted,
                fill_price=fill,
                source=quote.source,
            )
        )
        remaining -= qty
        if remaining == 0:
            break

    if total_qty == 0:
        return ExecutionReplayResult(
            candidate_id=intent.candidate_id,
            side=intent.side,
            status=ExecutionReplayStatus.UNVERIFIED_EXECUTION,
            requested_quantity=intent.quantity,
            filled_quantity=0,
            unfilled_quantity=intent.quantity,
            fill_ratio=0.0,
            delay_seconds=delay_seconds,
            spread_crossing_cost=0.0,
            impact_cost=0.0,
            commission_cost=0.0,
        )

    average_entry = total_notional / total_qty
    status = ExecutionReplayStatus.FILLED if total_qty == intent.quantity else ExecutionReplayStatus.PARTIAL_FILL
    stop_fill: float | None = None
    realized: float | None = None
    theoretical: float | None = None

    if stop_trigger_timestamp is not None:
        if stop_trigger_timestamp.tzinfo is None or stop_trigger_timestamp.utcoffset() is None:
            raise ValueError("stop_trigger_timestamp must be timezone-aware")
        stop_side = _stop_side(intent.side)
        stop_eligible = sorted((q for q in stop_quotes if q.timestamp >= stop_trigger_timestamp), key=lambda q: q.timestamp)
        if stop_eligible:
            quote = stop_eligible[0]
            raw_exit = _cross_price(stop_side, quote)
            stop_fill = _impacted_price(stop_side, raw_exit, intent.impact_bps)
            realized = _realized_r(intent, average_entry, stop_fill)
            theoretical = _theoretical_stop_r(intent)

    commission = total_qty * intent.commission_per_share
    return ExecutionReplayResult(
        candidate_id=intent.candidate_id,
        side=intent.side,
        status=status,
        requested_quantity=intent.quantity,
        filled_quantity=total_qty,
        unfilled_quantity=intent.quantity - total_qty,
        fill_ratio=_round(total_qty / intent.quantity),
        delay_seconds=delay_seconds,
        average_entry_price=_round(average_entry),
        implementation_shortfall_per_share=_round(_entry_shortfall(intent.side, average_entry, intent.reference_price)),
        spread_crossing_cost=_round(spread_cost) or 0.0,
        impact_cost=_round(impact_cost) or 0.0,
        commission_cost=_round(commission) or 0.0,
        fills=tuple(fills),
        stop_fill_price=_round(stop_fill),
        theoretical_stop_r=_round(theoretical),
        realized_r=_round(realized),
    )
