from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from morning_alpha.models import CatalystSnapshot, InstrumentSnapshot, MarketBar


class MarketDataProvider(Protocol):
    def instrument_snapshot(self, symbol: str, *, as_of: datetime) -> InstrumentSnapshot: ...

    def bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        limit: int,
        timeframe: str = "1Day",
    ) -> list[MarketBar]: ...

    def batch_snapshots(
        self,
        symbols: Sequence[str],
        *,
        as_of: datetime,
    ) -> dict[str, InstrumentSnapshot]: ...


class NewsProvider(Protocol):
    def catalysts(self, symbol: str, *, as_of: datetime, lookback_hours: int = 72) -> list[CatalystSnapshot]: ...


class OptionsProvider(Protocol):
    def option_chain(self, symbol: str, *, as_of: datetime) -> object: ...


class FundamentalProvider(Protocol):
    def fundamentals(self, symbol: str, *, as_of: datetime) -> dict[str, object]: ...


class MacroDataProvider(Protocol):
    def macro_snapshot(self, *, as_of: datetime) -> dict[str, object]: ...


class HistoricalProvider(MarketDataProvider, Protocol):
    def symbols(self, *, as_of: datetime) -> Sequence[str]: ...
