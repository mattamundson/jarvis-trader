"""Event normalization utilities for Phase 2."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from es_research.contracts import TradeEvent

NORMALIZED_TRADE_SCHEMA_VERSION = "es.normalized_trades.v1"
NORMALIZED_TRADE_METADATA_KEY = b"es_research.schema_version"
NORMALIZED_TRADE_COLUMNS = (
    "event_timestamp",
    "receive_timestamp",
    "instrument_id",
    "symbol",
    "price",
    "quantity",
    "aggressor_side",
    "sequence_number",
    "venue",
)


def normalize_trade_events(events: tuple[TradeEvent, ...]) -> tuple[dict[str, Any], ...]:
    """Sort and convert TradeEvent models into serializable normalized rows."""
    sorted_events = sorted(events, key=lambda event: (event.event_timestamp, event.sequence_number))
    return tuple(
        {
            "event_timestamp": event.event_timestamp,
            "receive_timestamp": event.receive_timestamp,
            "instrument_id": event.instrument_id,
            "symbol": event.symbol,
            "price": event.price,
            "quantity": event.quantity,
            "aggressor_side": event.aggressor_side.value,
            "sequence_number": event.sequence_number,
            "venue": event.venue,
        }
        for event in sorted_events
    )


def write_normalized_trades_parquet(rows: tuple[dict[str, Any], ...], path: Path) -> None:
    """Write normalized trade rows to Parquet using PyArrow when installed."""
    _require_pyarrow()
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    columns: dict[str, list[Any]] = {column: [] for column in NORMALIZED_TRADE_COLUMNS}
    for row in rows:
        for column in NORMALIZED_TRADE_COLUMNS:
            columns[column].append(row[column])
    schema = _normalized_trade_schema()
    table = pa.Table.from_pydict(columns, schema=schema)
    pq.write_table(table, path)


def read_normalized_trades_parquet(path: Path) -> tuple[dict[str, Any], ...]:
    """Read normalized trade rows from Parquet using PyArrow when installed."""
    _require_pyarrow()
    import pyarrow.parquet as pq

    if not path.is_file():
        raise FileNotFoundError(f"normalized Parquet file does not exist: {path}")
    table = pq.read_table(path)
    expected_schema = _normalized_trade_schema()
    actual_version = (table.schema.metadata or {}).get(NORMALIZED_TRADE_METADATA_KEY)
    if actual_version != NORMALIZED_TRADE_SCHEMA_VERSION.encode():
        raise ValueError(
            "normalized Parquet schema version mismatch: "
            f"expected {NORMALIZED_TRADE_SCHEMA_VERSION!r}, got {actual_version!r}"
        )
    if table.schema.remove_metadata() != expected_schema.remove_metadata():
        raise ValueError(
            "normalized Parquet physical schema mismatch: "
            f"expected {expected_schema.remove_metadata()}, got {table.schema.remove_metadata()}"
        )
    records = table.to_pylist()
    for record in records:
        if isinstance(record.get("price"), float):
            record["price"] = Decimal(str(record["price"]))
        if isinstance(record.get("quantity"), float):
            record["quantity"] = Decimal(str(record["quantity"]))
        for timestamp_column in ("event_timestamp", "receive_timestamp"):
            value = record.get(timestamp_column)
            if isinstance(value, datetime):
                record[timestamp_column] = value
    return tuple(records)


def _normalized_trade_schema() -> Any:
    """Build the canonical Arrow schema without importing PyArrow at module import time."""
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("event_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("receive_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("instrument_id", pa.string()),
            pa.field("symbol", pa.string()),
            pa.field("price", pa.decimal128(20, 9)),
            pa.field("quantity", pa.decimal128(20, 9)),
            pa.field("aggressor_side", pa.string()),
            pa.field("sequence_number", pa.int64()),
            pa.field("venue", pa.string()),
        ],
        metadata={NORMALIZED_TRADE_METADATA_KEY: NORMALIZED_TRADE_SCHEMA_VERSION.encode()},
    )


def _require_pyarrow() -> None:
    if find_spec("pyarrow") is None:
        raise ModuleNotFoundError(
            "PyArrow is required for normalized Parquet; install with `pip install -e '.[dev]'`."
        )
