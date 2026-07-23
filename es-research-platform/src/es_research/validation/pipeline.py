"""Validation helpers for the Phase 2 synthetic normalization pipeline."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from es_research.features.bars import Bar


def validate_normalized_trade_rows(rows: tuple[dict[str, Any], ...]) -> None:
    """Validate ordering and core invariants for normalized trade rows."""
    previous_key: tuple[datetime, int] | None = None
    for row in rows:
        timestamp = row["event_timestamp"]
        sequence_number = int(row["sequence_number"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("normalized trade rows must use timezone-aware timestamps")
        if Decimal(str(row["price"])) <= Decimal("0"):
            raise ValueError("normalized trade price must be positive")
        if Decimal(str(row["quantity"])) <= Decimal("0"):
            raise ValueError("normalized trade quantity must be positive")
        key = (timestamp, sequence_number)
        if previous_key is not None and key < previous_key:
            raise ValueError(
                "normalized trade rows must be sorted by timestamp and sequence_number"
            )
        previous_key = key


def validate_bars(bars: tuple[Bar, ...]) -> None:
    """Validate OHLCV bar invariants."""
    for bar in bars:
        if not (bar.high >= bar.open >= bar.low and bar.high >= bar.close >= bar.low):
            raise ValueError("bar OHLC values are internally inconsistent")
        if bar.volume <= Decimal("0"):
            raise ValueError("bar volume must be positive")
        if bar.trade_count <= 0:
            raise ValueError("bar trade_count must be positive")
        if bar.bar_end <= bar.bar_start:
            raise ValueError("bar_end must be after bar_start")
