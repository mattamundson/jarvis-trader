from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable, Sequence

from morning_alpha.models import InstrumentSnapshot, MarketBar, Session


class PointInTimeViolation(RuntimeError):
    """Raised when a caller explicitly requests data beyond its decision timestamp."""


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class FakeMarketDataProvider:
    def __init__(self, rows: dict[str, list[MarketBar]]) -> None:
        self._rows = {symbol: sorted(bars, key=lambda bar: bar.timestamp) for symbol, bars in rows.items()}

    @classmethod
    def from_rows(
        cls,
        symbol: str,
        rows: Iterable[tuple[datetime, float, float, float, float, float]],
        *,
        source: str = "fake",
    ) -> "FakeMarketDataProvider":
        normalized: dict[str, list[MarketBar]] = defaultdict(list)
        for ts, open_, high, low, close, volume in rows:
            _require_aware(ts, "bar timestamp")
            normalized[symbol].append(
                MarketBar(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(open_),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume),
                    session=Session.RTH,
                    source=source,
                    ingested_at=ts.astimezone(UTC),
                )
            )
        return cls(dict(normalized))

    def bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        limit: int,
        timeframe: str = "1Day",
        allow_future: bool = False,
    ) -> list[MarketBar]:
        del timeframe
        _require_aware(as_of, "as_of")
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self._rows.get(symbol, [])
        if allow_future and any(bar.timestamp > as_of for bar in rows):
            raise PointInTimeViolation(f"fixture for {symbol} contains data after {as_of.isoformat()}")
        eligible = [bar for bar in rows if bar.timestamp <= as_of]
        return eligible[-limit:]

    def instrument_snapshot(self, symbol: str, *, as_of: datetime) -> InstrumentSnapshot:
        _require_aware(as_of, "as_of")
        bars = self.bars(symbol, as_of=as_of, limit=20)
        if not bars:
            raise KeyError(f"no point-in-time data for {symbol} at {as_of.isoformat()}")
        latest = bars[-1]
        avg_shares = sum(bar.volume for bar in bars) / len(bars)
        avg_dollar = sum(bar.volume * bar.close for bar in bars) / len(bars)
        high_52w = max(bar.high for bar in bars)
        previous_close = bars[-2].close if len(bars) > 1 else None
        return InstrumentSnapshot(
            symbol=symbol,
            as_of=as_of,
            price=latest.close,
            previous_close=previous_close,
            avg_daily_shares_20d=avg_shares,
            avg_dollar_volume_20d=avg_dollar,
            high_52w=high_52w,
            source=latest.source,
            ingested_at=latest.ingested_at,
        )

    def batch_snapshots(
        self,
        symbols: Sequence[str],
        *,
        as_of: datetime,
    ) -> dict[str, InstrumentSnapshot]:
        _require_aware(as_of, "as_of")
        result: dict[str, InstrumentSnapshot] = {}
        for symbol in symbols:
            try:
                result[symbol] = self.instrument_snapshot(symbol, as_of=as_of)
            except KeyError:
                continue
        return result

    def symbols(self, *, as_of: datetime) -> Sequence[str]:
        _require_aware(as_of, "as_of")
        return tuple(sorted(symbol for symbol in self._rows if self.bars(symbol, as_of=as_of, limit=1)))
