"""
Unit tests for engine/analytics/bar_depth.py

Covers the pure coverage helpers (span_days, gap_stats, contaminated_pct,
pair_depth) with synthetic timestamps, and compute_bar_depth() against a
temp SQLite market_data_bars table with an injected screen_fn (so the test
needs no live DB and no real bar-quality predicate).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from analytics.bar_depth import (
    compute_bar_depth,
    contaminated_pct,
    gap_stats,
    pair_depth,
    span_days,
)


def _iso_series(start: str, n: int, step_minutes: int) -> list[str]:
    base = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    return [(base + timedelta(minutes=step_minutes * i)).isoformat() for i in range(n)]


# ── span_days ─────────────────────────────────────────────────────────────────


class TestSpanDays:
    def test_two_points_one_day(self):
        ts = ["2026-06-01T00:00:00+00:00", "2026-06-02T00:00:00+00:00"]
        assert span_days(ts) == pytest.approx(1.0)

    def test_single_point_is_zero(self):
        assert span_days(["2026-06-01T00:00:00+00:00"]) == 0.0

    def test_empty_is_zero(self):
        assert span_days([]) == 0.0

    def test_unsorted_input_ok(self):
        ts = ["2026-06-03T00:00:00+00:00", "2026-06-01T00:00:00+00:00"]
        assert span_days(ts) == pytest.approx(2.0)

    def test_ignores_unparseable(self):
        ts = ["garbage", "2026-06-01T00:00:00+00:00", None, "2026-06-02T00:00:00+00:00"]
        assert span_days(ts) == pytest.approx(1.0)


# ── gap_stats ─────────────────────────────────────────────────────────────────


class TestGapStats:
    def test_regular_series_no_gaps(self):
        ts = _iso_series("2026-06-01T00:00:00", 10, step_minutes=15)
        gap_count, max_gap_hours = gap_stats(ts)
        assert gap_count == 0
        assert max_gap_hours == pytest.approx(0.25)  # 15 min

    def test_one_large_gap_detected(self):
        # 5 regular 15-min bars, then a 5-hour jump, then 4 more.
        ts = _iso_series("2026-06-01T00:00:00", 5, step_minutes=15)
        jump_start = datetime.fromisoformat(ts[-1]).replace(tzinfo=timezone.utc) + timedelta(hours=5)
        ts += [(jump_start + timedelta(minutes=15 * i)).isoformat() for i in range(4)]
        gap_count, max_gap_hours = gap_stats(ts)
        assert gap_count == 1
        assert max_gap_hours == pytest.approx(5.0, abs=0.3)

    def test_fewer_than_two_points(self):
        assert gap_stats([]) == (0, 0.0)
        assert gap_stats(["2026-06-01T00:00:00+00:00"]) == (0, 0.0)


# ── contaminated_pct ──────────────────────────────────────────────────────────


class TestContaminatedPct:
    def test_basic(self):
        assert contaminated_pct(100, 3) == pytest.approx(3.0)

    def test_zero_rows(self):
        assert contaminated_pct(0, 0) == 0.0

    def test_all_rejected(self):
        assert contaminated_pct(8, 8) == pytest.approx(100.0)


# ── pair_depth ────────────────────────────────────────────────────────────────


class TestPairDepth:
    def test_shape_and_values(self):
        ts = _iso_series("2026-06-01T00:00:00", 4, step_minutes=60)
        rec = pair_depth("MES", "1h", ts, row_count=4, reject_count=1)
        assert rec["symbol"] == "MES"
        assert rec["interval"] == "1h"
        assert rec["rows"] == 4
        assert rec["span_days"] == pytest.approx(3 / 24)  # 3 hours
        assert rec["gap_count"] == 0
        assert rec["contaminated_pct"] == pytest.approx(25.0)
        assert rec["enforce_safe"] is False
        assert rec["first_ts"] is not None and rec["last_ts"] is not None

    def test_enforce_safe_when_clean(self):
        ts = _iso_series("2026-06-01T00:00:00", 3, step_minutes=60)
        rec = pair_depth("MGC", "1h", ts, row_count=3, reject_count=0)
        assert rec["enforce_safe"] is True
        assert rec["contaminated_pct"] == 0.0


# ── compute_bar_depth (DB orchestrator) ───────────────────────────────────────


def _make_db(tmp_path) -> str:
    db = tmp_path / "bars.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE market_data_bars ("
        "symbol TEXT, interval TEXT, ts_utc TEXT, open REAL, high REAL, low REAL, "
        "close REAL, volume REAL, source TEXT, fetched_at TEXT)"
    )
    rows = []
    for ts in _iso_series("2026-06-01T00:00:00", 6, step_minutes=60):
        rows.append(("MES", "1h", ts, 100.0, 101.0, 99.0, 100.5, 1000, "tv", ts))
    for ts in _iso_series("2026-06-01T00:00:00", 3, step_minutes=60):
        rows.append(("MGC", "1h", ts, 2000.0, 2001.0, 1999.0, 2000.5, 50, "tv", ts))
    conn.executemany(
        "INSERT INTO market_data_bars VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return str(db)


class TestComputeBarDepth:
    def test_orchestrator_with_stub_screen(self, tmp_path):
        db_path = _make_db(tmp_path)
        # Stub screen_fn: reject the first MES row only.
        def stub_screen(rows):
            return [r for r in rows if r[0] == "MES"][:1]

        out = compute_bar_depth(db_path=db_path, screen_fn=stub_screen)
        assert set(out.keys()) == {"pairs", "summary", "timestamp"}
        pairs = {p["symbol"]: p for p in out["pairs"]}
        assert set(pairs) == {"MES", "MGC"}
        assert pairs["MES"]["rows"] == 6
        assert pairs["MGC"]["rows"] == 3
        # stub rejects exactly 1 MES row → 1/6 contaminated, MGC clean.
        assert pairs["MES"]["contaminated_pct"] == pytest.approx(round(100 / 6, 4))
        assert pairs["MGC"]["enforce_safe"] is True

        summary = out["summary"]
        assert summary["pair_count"] == 2
        assert summary["symbol_count"] == 2
        assert summary["total_rows"] == 9
        assert summary["total_rejects"] == 1

    def test_pairs_sorted(self, tmp_path):
        db_path = _make_db(tmp_path)
        out = compute_bar_depth(db_path=db_path, screen_fn=lambda rows: [])
        symbols = [p["symbol"] for p in out["pairs"]]
        assert symbols == sorted(symbols)
