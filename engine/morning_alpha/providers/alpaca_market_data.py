from __future__ import annotations

import os
from datetime import UTC, datetime, time
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from morning_alpha.models import InstrumentSnapshot, MarketBar, Session

_EASTERN = ZoneInfo("America/New_York")


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def classify_session(timestamp: datetime) -> Session:
    """Classify a timezone-aware U.S. equity timestamp by Eastern session."""
    _require_aware(timestamp, "timestamp")
    local = timestamp.astimezone(_EASTERN)
    t = local.time().replace(tzinfo=None)
    if time(4, 0) <= t < time(9, 30):
        return Session.PREMARKET
    if time(9, 30) <= t < time(16, 0):
        return Session.RTH
    if time(16, 0) <= t < time(20, 0):
        return Session.AFTER_HOURS
    return Session.CLOSED


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj[name]
    return getattr(obj, name)


def normalize_alpaca_bar(
    symbol: str,
    raw: Any,
    *,
    ingested_at: datetime | None = None,
) -> MarketBar:
    ts = _value(raw, "timestamp")
    _require_aware(ts, "vendor timestamp")
    ingested = ingested_at or datetime.now(UTC)
    _require_aware(ingested, "ingested_at")
    return MarketBar(
        symbol=symbol,
        timestamp=ts.astimezone(UTC),
        open=float(_value(raw, "open")),
        high=float(_value(raw, "high")),
        low=float(_value(raw, "low")),
        close=float(_value(raw, "close")),
        volume=float(_value(raw, "volume")),
        session=classify_session(ts),
        source="alpaca",
        ingested_at=ingested.astimezone(UTC),
    )


class AlpacaMarketDataProvider:
    """Point-in-time-safe Alpaca adapter.

    The Alpaca SDK is imported lazily so research/unit tests can run without live
    vendor packages. A test/client double may be injected via ``client``.
    """

    def __init__(self, client: Any | None = None, *, feed: str | None = None) -> None:
        self.feed = feed or os.getenv("MORNING_ALPHA_ALPACA_FEED", "sip")
        self._client = client or self._build_client()

    @staticmethod
    def _build_client() -> Any:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:  # pragma: no cover - dependency smoke-tested in CI/runtime
            raise RuntimeError("alpaca-py is required for live Alpaca market data") from exc
        key = os.getenv("MORNING_ALPHA_ALPACA_API_KEY")
        secret = os.getenv("MORNING_ALPHA_ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("MORNING_ALPHA_ALPACA_API_KEY/SECRET_KEY are required")
        return StockHistoricalDataClient(key, secret)

    def _raw_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        limit: int,
        timeframe: str,
    ) -> list[Any]:
        if hasattr(self._client, "get_bars"):
            return list(
                self._client.get_bars(
                    symbol=symbol,
                    as_of=as_of,
                    limit=limit,
                    timeframe=timeframe,
                    feed=self.feed,
                )
            )
        try:  # pragma: no cover - exercised only with alpaca-py installed
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            tf = getattr(TimeFrame, timeframe, TimeFrame.Day)
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                end=as_of,
                limit=limit,
                feed=self.feed,
            )
            response = self._client.get_stock_bars(request)
            data = response.data if hasattr(response, "data") else response
            return list(data.get(symbol, []))
        except ImportError as exc:
            raise RuntimeError("alpaca-py is required for live Alpaca market data") from exc

    def bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        limit: int,
        timeframe: str = "Day",
    ) -> list[MarketBar]:
        _require_aware(as_of, "as_of")
        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized = [
            normalize_alpaca_bar(symbol, raw)
            for raw in self._raw_bars(
                symbol,
                as_of=as_of,
                limit=limit,
                timeframe=timeframe,
            )
        ]
        eligible = [bar for bar in normalized if bar.timestamp <= as_of.astimezone(UTC)]
        return sorted(eligible, key=lambda bar: bar.timestamp)[-limit:]

    def instrument_snapshot(self, symbol: str, *, as_of: datetime) -> InstrumentSnapshot:
        bars = self.bars(symbol, as_of=as_of, limit=252, timeframe="Day")
        if not bars:
            raise KeyError(f"no Alpaca bars for {symbol} at {as_of.isoformat()}")
        latest = bars[-1]
        last20 = bars[-20:]
        return InstrumentSnapshot(
            symbol=symbol,
            as_of=as_of,
            price=latest.close,
            previous_close=bars[-2].close if len(bars) > 1 else None,
            avg_daily_shares_20d=sum(b.volume for b in last20) / len(last20),
            avg_dollar_volume_20d=sum(b.volume * b.close for b in last20) / len(last20),
            high_52w=max(b.high for b in bars),
            source="alpaca",
            ingested_at=max(b.ingested_at for b in bars),
        )

    def batch_snapshots(
        self,
        symbols: Sequence[str],
        *,
        as_of: datetime,
    ) -> dict[str, InstrumentSnapshot]:
        result: dict[str, InstrumentSnapshot] = {}
        for symbol in symbols:
            try:
                result[symbol] = self.instrument_snapshot(symbol, as_of=as_of)
            except KeyError:
                continue
        return result
