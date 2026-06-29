"""Tests for engine.scripts.reconcile_bars -- the B4 cache-vs-SQLite reconciler.

Each test builds a temp cache CSV + a temp SQLite market_data_bars table, points
the reconciler at both, and asserts the right finding (or clean run) is produced.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import reconcile_bars as rb

SYM = "MES"
TS = [
    "2026-05-07T09:00:00",
    "2026-05-07T10:00:00",
    "2026-05-07T11:00:00",
    "2026-05-07T12:00:00",
    "2026-05-07T13:00:00",
]


def _write_cache(tmp_path: Path, rows: list[dict]) -> Path:
    csv = tmp_path / f"{SYM}_test_1h.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    return csv


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE market_data_bars (
            symbol TEXT NOT NULL, interval TEXT NOT NULL, ts_utc TEXT NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
            close REAL NOT NULL, volume REAL, source TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, ts_utc)
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _insert(db: Path, ts: str, ohlc: tuple, source: str) -> None:
    o, h, lo, c = ohlc
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO market_data_bars VALUES (?,?,?,?,?,?,?,?,?,?)",
        (SYM, "1h", ts, o, h, lo, c, 1.0, source, "2026-05-07T00:00:00"),
    )
    conn.commit()
    conn.close()


def _cache_rows() -> list[dict]:
    return [
        {"timestamp": t, "open": 5300.0 + i, "high": 5310.0 + i,
         "low": 5295.0 + i, "close": 5305.0 + i, "volume": 100 + i}
        for i, t in enumerate(TS)
    ]


@pytest.fixture
def patch_cache(tmp_path, monkeypatch):
    """Point the reconciler's cache lookup at a temp CSV we control."""
    def _setup(rows):
        csv = _write_cache(tmp_path, rows)
        monkeypatch.setattr(rb, "_find_all_csvs", lambda sym: [csv])
        return csv
    return _setup


def test_clean_match_no_findings(tmp_path, patch_cache):
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    for i, t in enumerate(TS):
        _insert(db, t, (5300.0 + i, 5310.0 + i, 5295.0 + i, 5305.0 + i), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["error"] is None
    assert res["matched"] == 5
    assert res["match_frac"] == 1.0
    assert res["mismatches"] == 0
    assert res["cache_only"] == 0
    assert res["findings"] == []


def test_cache_sourced_corruption_flagged(tmp_path, patch_cache):
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    for i, t in enumerate(TS):
        # bar index 2 is corrupted: close +1% above the CSV (> CACHE_TOL 0.05%)
        bump = 1.01 if i == 2 else 1.0
        _insert(db, t, (5300.0 + i, 5310.0 + i, 5295.0 + i, (5305.0 + i) * bump), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["cache_src_mismatches"] == 1
    assert res["mismatches"] == 1
    assert any("DIVERGE from the CSV" in f for f in res["findings"])


def test_uniform_roll_basis_not_flagged_as_corruption(tmp_path, patch_cache):
    """A uniform per-bar offset across ALL OHLC (futures roll / back-adjustment
    basis) is honest divergence, not corruption -- it must NOT raise a finding.
    This is the 2026-06 MES March-roll false alarm (~0.78% uniform same-sign shift
    on 34 cache-sourced bars). Counted as a basis divergence, not a mismatch."""
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    for i, t in enumerate(TS):
        # bar index 2: every OHLC shifted +0.8% (same sign, equal proportion)
        m = 1.008 if i == 2 else 1.0
        _insert(db, t, ((5300.0 + i) * m, (5310.0 + i) * m,
                        (5295.0 + i) * m, (5305.0 + i) * m), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["cache_src_mismatches"] == 0
    assert res["mismatches"] == 0
    assert res["cache_basis_divergences"] == 1
    assert not any("DIVERGE from the CSV" in f for f in res["findings"])


def test_nonuniform_offset_still_corruption(tmp_path, patch_cache):
    """A shift on only SOME OHLC (large spread) is NOT a roll basis -- it stays a
    corruption finding even if same-signed and within the roll-gap cap."""
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    for i, t in enumerate(TS):
        if i == 2:
            # open/close +0.8%, high/low untouched -> spread huge -> not basis
            _insert(db, t, ((5300.0 + i) * 1.008, 5310.0 + i,
                            5295.0 + i, (5305.0 + i) * 1.008), "cache")
        else:
            _insert(db, t, (5300.0 + i, 5310.0 + i, 5295.0 + i, 5305.0 + i), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["cache_basis_divergences"] == 0
    assert res["cache_src_mismatches"] == 1
    assert any("DIVERGE from the CSV" in f for f in res["findings"])


def test_live_gross_divergence_flagged_small_ignored(tmp_path, patch_cache):
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    for i, t in enumerate(TS):
        if i == 1:
            mult = 1.10           # live row +10% (> LIVE_TOL 5%) -> flagged
        elif i == 3:
            mult = 1.01           # live row +1% (< LIVE_TOL) -> benign, NOT flagged
        else:
            mult = 1.0
        _insert(db, t, (5300.0 + i, 5310.0 + i, 5295.0 + i, (5305.0 + i) * mult), "ibkr")
    res = rb.reconcile_symbol(SYM, db_path=db)
    # exactly one gross live mismatch, zero cache-sourced
    assert res["cache_src_mismatches"] == 0
    assert res["mismatches"] == 1
    assert any("diverge grossly" in f for f in res["findings"])


def test_coverage_gap_flagged(tmp_path, patch_cache):
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    # insert only 3 of 5 cache timestamps -> 40% missing (> MISSING_WARN_FRAC 10%)
    for i in (0, 1, 2):
        _insert(db, TS[i], (5300.0 + i, 5310.0 + i, 5295.0 + i, 5305.0 + i), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["cache_only"] == 2
    assert res["mismatches"] == 0
    assert any("missing from SQLite" in f for f in res["findings"])


def test_disjoint_keys_flag_unverified(tmp_path, patch_cache):
    patch_cache(_cache_rows())
    db = _make_db(tmp_path)
    # SQLite rows IN the cache window [09:00,13:00] but off the hourly grid (:30),
    # so they load but key-match no cache bar -> overlap ~0, unverified.
    for hh in (9, 10, 11, 12):
        _insert(db, f"2026-05-07T{hh:02d}:30:00",
                (5300.0, 5310.0, 5295.0, 5305.0), "cache")
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["sqlite_rows"] > 0          # rows loaded, just non-matching
    assert res["matched"] == 0
    assert res["match_frac"] is not None and res["match_frac"] < rb.MIN_MATCH_FRAC
    assert any("keyed" in f for f in res["findings"])


def test_missing_cache_csv_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "_find_all_csvs", lambda sym: [])
    db = _make_db(tmp_path)
    res = rb.reconcile_symbol(SYM, db_path=db)
    assert res["error"] is not None
    assert "no cache CSV" in res["error"]
