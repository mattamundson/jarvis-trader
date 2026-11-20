from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from morning_alpha.models import InstrumentSnapshot, MarketBar, Session


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def historical_bars_sql() -> str:
    return """
        SELECT symbol, timestamp, open, high, low, close, volume, session, source, ingested_at
        FROM read_parquet(?)
        WHERE symbol = ? AND timestamp <= ?
        ORDER BY timestamp DESC
        LIMIT ?
    """.strip()


class ParquetHistoricalProvider:
    """Point-in-time historical market-data adapter backed by DuckDB/Parquet."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.data_dir = Path(
            data_dir or os.getenv("MORNING_ALPHA_DATA_DIR", "./data/morning_alpha")
        )
        self._connection_factory = connection_factory or self._default_connection

    @staticmethod
    def _default_connection() -> Any:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency smoke-tested in CI/runtime
            raise RuntimeError("duckdb is required for Parquet historical data") from exc
        return duckdb.connect(database=":memory:")

    @property
    def bars_glob(self) -> str:
        return str(self.data_dir / "bars" / "*.parquet")

    def bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        limit: int,
        timeframe: str = "1Day",
    ) -> list[MarketBar]:
        del timeframe
        _require_aware(as_of, "as_of")
        if limit <= 0:
            raise ValueError("limit must be positive")
        conn = self._connection_factory()
        rows = conn.execute(
            historical_bars_sql(),
            [self.bars_glob, symbol, as_of.astimezone(UTC), limit],
        ).fetchall()
        bars = [
            MarketBar(
                symbol=row[0],
                timestamp=row[1],
                open=row[2],
                high=row[3],
                low=row[4],
                close=row[5],
                volume=row[6],
                session=Session(row[7]),
                source=row[8],
                ingested_at=row[9],
            )
            for row in reversed(rows)
        ]
        if any(bar.timestamp > as_of for bar in bars):
            raise RuntimeError("historical provider returned future data despite SQL predicate")
        return bars

    def instrument_snapshot(self, symbol: str, *, as_of: datetime) -> InstrumentSnapshot:
        bars = self.bars(symbol, as_of=as_of, limit=252)
        if not bars:
            raise KeyError(f"no historical bars for {symbol} at {as_of.isoformat()}")
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
            source=latest.source,
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

    def symbols(self, *, as_of: datetime) -> Sequence[str]:
        _require_aware(as_of, "as_of")
        conn = self._connection_factory()
        sql = "SELECT DISTINCT symbol FROM read_parquet(?) WHERE timestamp <= ? ORDER BY symbol"
        rows = conn.execute(sql, [self.bars_glob, as_of.astimezone(UTC)]).fetchall()
        return tuple(row[0] for row in rows)
