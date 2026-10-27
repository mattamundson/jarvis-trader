from datetime import UTC, datetime

from morning_alpha.providers.historical_parquet import (
    ParquetHistoricalProvider,
    historical_bars_sql,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return FakeResult(self.rows)


def test_historical_sql_pushes_as_of_predicate_into_duckdb():
    sql = historical_bars_sql().lower()
    assert "timestamp <= ?" in sql
    assert "where symbol = ?" in sql


def test_provider_passes_as_of_as_sql_parameter_and_returns_chronological_bars(tmp_path):
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    rows = [
        (
            "XYZ",
            datetime(2026, 9, 15, 13, 59, tzinfo=UTC),
            100,
            102,
            99,
            101,
            1000,
            "rth",
            "fixture",
            datetime(2026, 9, 15, 14, 0, tzinfo=UTC),
        ),
        (
            "XYZ",
            datetime(2026, 9, 15, 13, 58, tzinfo=UTC),
            99,
            101,
            98,
            100,
            900,
            "rth",
            "fixture",
            datetime(2026, 9, 15, 14, 0, tzinfo=UTC),
        ),
    ]
    conn = FakeConnection(rows)
    provider = ParquetHistoricalProvider(tmp_path, connection_factory=lambda: conn)
    bars = provider.bars("XYZ", as_of=as_of, limit=2)
    assert [bar.close for bar in bars] == [100, 101]
    sql, params = conn.calls[0]
    assert "timestamp <= ?" in sql.lower()
    assert params[2] == as_of
