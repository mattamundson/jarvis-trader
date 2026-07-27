"""Deterministic synthetic trade-event generation for Phase 2 pipeline tests.

The generated records are artificial engineering fixtures, not market data and not
investment research inputs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from es_research.contracts import AggressorSide, TradeEvent, require_utc


@dataclass(frozen=True)
class SyntheticTradeConfig:
    instrument_id: str
    symbol: str
    venue: str
    start_timestamp: datetime
    event_count: int
    interval_seconds: int
    start_price: Decimal
    quantity: Decimal
    random_seed: int

    def __post_init__(self) -> None:
        require_utc(self.start_timestamp)
        if self.event_count <= 0:
            raise ValueError("event_count must be positive")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.start_price <= Decimal("0"):
            raise ValueError("start_price must be positive")
        if self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")


def generate_synthetic_trades(config: SyntheticTradeConfig) -> tuple[TradeEvent, ...]:
    """Generate deterministic, ordered synthetic TradeEvent records."""
    rng = random.Random(config.random_seed)
    price = config.start_price
    events: list[TradeEvent] = []
    for index in range(config.event_count):
        step_ticks = Decimal(rng.choice([-1, 0, 1]))
        price = max(Decimal("0.25"), price + step_ticks * Decimal("0.25"))
        event_timestamp = config.start_timestamp + timedelta(
            seconds=index * config.interval_seconds
        )
        events.append(
            TradeEvent(
                event_timestamp=event_timestamp,
                receive_timestamp=event_timestamp + timedelta(milliseconds=5),
                instrument_id=config.instrument_id,
                symbol=config.symbol,
                price=price,
                quantity=config.quantity,
                aggressor_side=AggressorSide.BUY if index % 2 == 0 else AggressorSide.SELL,
                sequence_number=index + 1,
                venue=config.venue,
            )
        )
    return tuple(events)
