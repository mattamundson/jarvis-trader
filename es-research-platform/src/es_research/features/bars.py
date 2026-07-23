"""OHLCV bar construction from normalized, session-assigned trade rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from es_research.contracts import require_utc


@dataclass(frozen=True)
class Bar:
    instrument_id: str
    symbol: str
    session_id: str
    bar_start: datetime
    bar_end: datetime
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int


def floor_timestamp(timestamp: datetime, interval: timedelta) -> datetime:
    """Floor a UTC timestamp to an interval boundary measured from Unix epoch."""
    normalized = require_utc(timestamp)
    seconds = int(interval.total_seconds())
    if seconds <= 0:
        raise ValueError("bar interval must be positive")
    epoch_seconds = int(normalized.timestamp())
    floored_seconds = epoch_seconds - (epoch_seconds % seconds)
    return datetime.fromtimestamp(floored_seconds, tz=normalized.tzinfo)


def build_time_bars(
    rows: tuple[dict[str, Any], ...], *, interval: timedelta = timedelta(minutes=5)
) -> tuple[Bar, ...]:
    """Build deterministic OHLCV bars from sorted trade rows."""
    sorted_rows = sorted(rows, key=lambda row: (row["event_timestamp"], row["sequence_number"]))
    buckets: dict[tuple[str, str, datetime], list[dict[str, Any]]] = {}
    for row in sorted_rows:
        for required in (
            "instrument_id",
            "symbol",
            "session_id",
            "event_timestamp",
            "price",
            "quantity",
        ):
            if required not in row:
                raise KeyError(f"normalized event row missing {required}")
        bar_start = floor_timestamp(row["event_timestamp"], interval)
        key = (str(row["instrument_id"]), str(row["session_id"]), bar_start)
        buckets.setdefault(key, []).append(row)

    bars: list[Bar] = []
    for (instrument_id, session_id, bar_start), bucket_rows in sorted(buckets.items()):
        prices = [Decimal(str(row["price"])) for row in bucket_rows]
        quantities = [Decimal(str(row["quantity"])) for row in bucket_rows]
        first = bucket_rows[0]
        bars.append(
            Bar(
                instrument_id=instrument_id,
                symbol=str(first["symbol"]),
                session_id=session_id,
                bar_start=bar_start,
                bar_end=bar_start + interval,
                timeframe=f"{int(interval.total_seconds() // 60)}m",
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum(quantities, Decimal("0")),
                trade_count=len(bucket_rows),
            )
        )
    return tuple(bars)
