"""Databento trade-record conversion at the bronze-to-silver boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from numbers import Integral
from pathlib import Path
from typing import Any

from es_research.contracts import AggressorSide, TradeEvent
from es_research.normalization.events import normalize_trade_events

DBN_FIXED_PRICE_SCALE = Decimal("0.000000001")


def decode_databento_trades(path: Path) -> tuple[dict[str, Any], ...]:
    """Decode a DBN file through the optional Databento SDK into plain records."""
    if not path.is_file():
        raise FileNotFoundError(f"Databento DBN file does not exist: {path}")
    import databento as db

    frame = db.DBNStore.from_file(path).to_df(
        pretty_px=False,
        pretty_ts=False,
        map_symbols=False,
    )
    records = frame.reset_index().to_dict(orient="records")
    return tuple(dict(record) for record in records)


def normalize_databento_trades(
    records: Iterable[Mapping[str, Any]], *, symbol_by_instrument: Mapping[int, str]
) -> tuple[dict[str, Any], ...]:
    """Convert decoded Databento trade records into canonical silver rows.

    ``price`` is interpreted as DBN's fixed-precision integer representation.
    ``side`` uses the resting-book side: an ask-side trade is buyer-aggressed and
    a bid-side trade is seller-aggressed.
    """
    events: list[TradeEvent] = []
    for record in records:
        instrument_id = _required_int(record, "instrument_id")
        try:
            symbol = symbol_by_instrument[instrument_id]
        except KeyError as exc:
            raise ValueError(f"missing symbol mapping for instrument_id {instrument_id}") from exc
        events.append(
            TradeEvent(
                event_timestamp=_dbn_timestamp(record["ts_event"]),
                receive_timestamp=(
                    _dbn_timestamp(record["ts_recv"]) if record.get("ts_recv") is not None else None
                ),
                instrument_id=str(instrument_id),
                symbol=symbol,
                price=Decimal(_required_int(record, "price")) * DBN_FIXED_PRICE_SCALE,
                quantity=Decimal(_required_int(record, "size")),
                aggressor_side=_aggressor_side(record.get("side")),
                sequence_number=_required_int(record, "sequence"),
                venue=str(record.get("publisher_id", "Databento")),
            )
        )
    return normalize_trade_events(tuple(events))


def _dbn_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Databento datetime timestamps must be timezone-aware")
        return value.astimezone(UTC)
    if isinstance(value, Integral) and not isinstance(value, bool):
        seconds, nanoseconds = divmod(int(value), 1_000_000_000)
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=nanoseconds // 1_000)
    raise TypeError(f"unsupported Databento timestamp type: {type(value).__name__}")


def _required_int(record: Mapping[str, Any], name: str) -> int:
    try:
        value = record[name]
    except KeyError as exc:
        raise ValueError(f"Databento trade record missing {name}") from exc
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"Databento trade field {name} must be an integer")
    return int(value)


def _aggressor_side(value: object) -> AggressorSide:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    normalized = str(value).upper() if value is not None else "N"
    if normalized in {"A", "ASK"}:
        return AggressorSide.BUY
    if normalized in {"B", "BID"}:
        return AggressorSide.SELL
    if normalized in {"N", "NONE", "UNKNOWN"}:
        return AggressorSide.UNKNOWN
    raise ValueError(f"unsupported Databento side: {value!r}")
