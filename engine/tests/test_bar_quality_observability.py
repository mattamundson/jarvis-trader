"""Tests for bar-quality rejection observability (migration 039 + recorder).

Covers the data layer that feeds GET /analytics/bar-quality:
  - _categorize_sanity_reason maps free-text reasons to machine categories
  - _record_rejections aggregates by category and persists counts
  - the endpoint's aggregation query produces the expected per-reason/symbol shape
  - a DB predating migration 039 never raises (observability must not break writes)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from data.bars_repository import (  # noqa: E402
    _categorize_sanity_reason,
    _record_rejections,
)
from database.migrations import migration_039  # noqa: E402


def _make_db(path: Path, with_table: bool = True) -> None:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    if with_table:
        migration_039(conn)
    conn.close()


class TestCategorizeSanityReason:
    def test_sentinel(self):
        assert _categorize_sanity_reason(
            "IB snapshot sentinel flat bar at 100.5"
        ) == "IB_SENTINEL"

    def test_price_band(self):
        assert _categorize_sanity_reason(
            "close 100.5 outside plausible band (500.0, 50000.0) for MES"
        ) == "PRICE_BAND"

    def test_neighbor_jump(self):
        assert _categorize_sanity_reason(
            "close 100.5 is a 98% jump vs reference 7400 (max 50%)"
        ) == "NEIGHBOR_JUMP"

    def test_nonfinite(self):
        assert _categorize_sanity_reason("non-positive/non-finite close=-1") == "NONFINITE"

    def test_unknown_falls_through(self):
        assert _categorize_sanity_reason("something brand new") == "OTHER"


class TestRecordRejections:
    def test_aggregates_by_category(self, tmp_path):
        db = tmp_path / "bq.db"
        _make_db(db)
        items = [
            ("IB_SENTINEL", "flat bar at 100.5"),
            ("IB_SENTINEL", "flat bar at 100.5"),
            ("PRICE_BAND", "close 100.5 outside band"),
        ]
        _record_rejections("MCL", "1m", "ibkr", "sanity", items, db)

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT reason, count, symbol, source, path FROM bar_quality_rejections "
            "ORDER BY reason"
        ).fetchall()
        conn.close()

        # one row per category, sentinel aggregated to count=2
        assert len(rows) == 2
        by = {r["reason"]: r for r in rows}
        assert by["IB_SENTINEL"]["count"] == 2
        assert by["PRICE_BAND"]["count"] == 1
        assert by["IB_SENTINEL"]["symbol"] == "MCL"
        assert by["IB_SENTINEL"]["source"] == "ibkr"
        assert by["IB_SENTINEL"]["path"] == "sanity"

    def test_endpoint_aggregation_query(self, tmp_path):
        """Mirror the /analytics/bar-quality aggregation to lock the shape."""
        db = tmp_path / "bq.db"
        _make_db(db)
        _record_rejections("MES", "1m", "polygon", "gate",
                           [("RANGE_EXPLOSION", "range=0.6"), ("RANGE_EXPLOSION", "range=0.7")], db)
        _record_rejections("MCL", "1m", "ibkr", "sanity",
                           [("IB_SENTINEL", "100.5")], db)

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, path, reason, count FROM bar_quality_rejections"
        ).fetchall()
        conn.close()

        by_reason: dict[str, int] = {}
        by_symbol: dict[str, int] = {}
        by_path = {"sanity": 0, "gate": 0}
        total = 0
        for r in rows:
            c = int(r["count"])
            total += c
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + c
            by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0) + c
            by_path[r["path"]] += c

        assert total == 3
        assert by_reason["RANGE_EXPLOSION"] == 2
        assert by_reason["IB_SENTINEL"] == 1
        assert by_symbol == {"MES": 2, "MCL": 1}
        assert by_path == {"sanity": 1, "gate": 2}

    def test_missing_table_is_silent(self, tmp_path):
        """A DB without the table (pre-migration) must not raise."""
        db = tmp_path / "no_table.db"
        _make_db(db, with_table=False)
        # must return without raising even though bar_quality_rejections is absent
        _record_rejections("MES", "1m", "ibkr", "gate", [("NONFINITE", "nan")], db)

    def test_empty_items_noop(self, tmp_path):
        db = tmp_path / "bq.db"
        _make_db(db)
        _record_rejections("MES", "1m", "ibkr", "gate", [], db)
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM bar_quality_rejections").fetchone()[0]
        conn.close()
        assert n == 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
