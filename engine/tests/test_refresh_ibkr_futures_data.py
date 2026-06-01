"""Regression tests for engine/backtest/refresh_ibkr_futures_data.py.

Locks in the 2026-05-20 tz-aware/naive normalization fix in
parse_csv_date_range — MES + MGC cached CSVs store '+00:00' offsets while
MNQ + MCL store naive timestamps. Pre-fix, the MES/MGC path errored with
"can't subtract offset-naive and offset-aware datetimes" when computing
the gap against datetime.now(UTC).replace(tzinfo=None).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Make engine/ importable when test is run from engine root
_ENGINE = Path(__file__).resolve().parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.refresh_ibkr_futures_data import parse_csv_date_range  # noqa: E402


def _write_csv(path: Path, timestamps: list[str]) -> None:
    """Write a minimal OHLCV CSV with the given timestamp strings."""
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1000.0] * len(timestamps),
        }
    )
    df.to_csv(path, index=False)


class TestParseCsvDateRange:
    """The pre-2026-05-20 production bug: MES + MGC CSVs returned tz-aware
    datetimes; downstream subtraction against tz-naive `now` raised
    ValueError; refresh silently failed for those two symbols.
    """

    def test_tz_aware_csv_returns_naive_datetime(self, tmp_path: Path) -> None:
        """MES/MGC-style: timestamps with '+00:00' offset."""
        csv = tmp_path / "MES_2024-04-26_2026-05-07_1h.csv"
        _write_csv(csv, ["2024-04-26 05:00:00+00:00", "2026-05-07 04:00:00+00:00"])

        first, last = parse_csv_date_range(csv)

        assert first.tzinfo is None, "first datetime must be tz-naive"
        assert last.tzinfo is None, "last datetime must be tz-naive"
        assert first.year == 2024 and first.month == 4 and first.day == 26
        assert last.year == 2026 and last.month == 5 and last.day == 7

    def test_tz_naive_csv_returns_naive_datetime(self, tmp_path: Path) -> None:
        """MNQ/MCL-style: timestamps without offset suffix."""
        csv = tmp_path / "MNQ_2026-01-09_2026-05-20_1h.csv"
        _write_csv(csv, ["2026-01-09 00:00:00", "2026-05-20 08:00:00"])

        first, last = parse_csv_date_range(csv)

        assert first.tzinfo is None
        assert last.tzinfo is None
        assert last.year == 2026 and last.month == 5 and last.day == 20

    def test_subtraction_with_now_naive_does_not_raise(self, tmp_path: Path) -> None:
        """Regression lock: the actual failure mode was the gap computation.

        Pre-fix: `now - last_dt` raised TypeError when last_dt was tz-aware.
        This test exercises both inputs through the real callable path.
        """
        # Both CSV shapes — must work identically downstream
        aware_csv = tmp_path / "MES_2024-04-26_2026-05-07_1h.csv"
        naive_csv = tmp_path / "MNQ_2026-01-09_2026-05-20_1h.csv"
        _write_csv(aware_csv, ["2024-04-26 05:00:00+00:00", "2026-05-07 04:00:00+00:00"])
        _write_csv(naive_csv, ["2026-01-09 00:00:00", "2026-05-20 08:00:00"])

        _, mes_last = parse_csv_date_range(aware_csv)
        _, mnq_last = parse_csv_date_range(naive_csv)

        # Both must subtract cleanly from a naive `now` (the production callsite)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        mes_gap_hours = (now_naive - mes_last).total_seconds() / 3600
        mnq_gap_hours = (now_naive - mnq_last).total_seconds() / 3600

        # Sanity: gaps are positive (cache last bar is in the past)
        assert mes_gap_hours > 0
        assert mnq_gap_hours > 0

    def test_datetime_column_name_fallback(self, tmp_path: Path) -> None:
        """Handles 'datetime' column as well as 'timestamp'."""
        csv = tmp_path / "MES_test_1h.csv"
        df = pd.DataFrame(
            {
                "datetime": ["2026-05-07 04:00:00+00:00", "2026-05-08 04:00:00+00:00"],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000.0, 1100.0],
            }
        )
        df.to_csv(csv, index=False)

        first, last = parse_csv_date_range(csv)

        assert first.tzinfo is None
        assert last.tzinfo is None

    def test_case_insensitive_column_lookup(self, tmp_path: Path) -> None:
        """Lower-casing of column names happens before lookup."""
        csv = tmp_path / "MGC_test_1h.csv"
        df = pd.DataFrame(
            {
                "TimeStamp": ["2026-05-07 04:00:00+00:00"],
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000.0],
            }
        )
        df.to_csv(csv, index=False)

        first, last = parse_csv_date_range(csv)

        assert first.tzinfo is None
        assert first == last  # single-row CSV
