"""Tests for engine.data.bar_quality_gate — write-time bar-quality screening.

Covers the pure per-bar screen (screen_bars) against each contamination class
from the 2026-06-11 edge re-assessment, the no-false-positive guarantee on real
trends/gaps, and the shadow/enforce integration through bars_repository.save_bars.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bar_quality_gate import apply_gate, screen_bars
from data.bars_repository import load_bars, save_bars

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(ts, o, h, low, c, source="ibkr"):
    """Build a save_bars-layout row tuple:
    (symbol, interval, ts_iso, open, high, low, close, volume, source, fetched_at)
    """
    return ("MES", "1h", ts, o, h, low, c, 1000.0, source, "2026-06-12T00:00:00")


def _clean_rows(n=5, base=5300.0):
    rows = []
    for i in range(n):
        ts = f"2026-05-07T{9 + i:02d}:00:00"
        px = base + i
        rows.append(_row(ts, px, px + 10, px - 10, px + 5))
    return rows


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
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


def _bars_df(specs):
    """specs: list of (hour, open, high, low, close)."""
    return pd.DataFrame(
        [
            {
                "timestamp": datetime(2026, 5, 7, hr, 0, 0, tzinfo=timezone.utc),
                "open": o, "high": h, "low": low, "close": c, "volume": 1000.0,
            }
            for hr, o, h, low, c in specs
        ]
    )


# ---------------------------------------------------------------------------
# screen_bars — pure per-bar screen
# ---------------------------------------------------------------------------


def test_clean_bars_pass():
    assert screen_bars(_clean_rows()) == []


def test_nonpositive_price_rejected():
    rows = _clean_rows()
    rows[2] = _row("2026-05-07T11:00:00", 0.0, 5310.0, -1.0, 5305.0)
    rejects = screen_bars(rows)
    assert [r.index for r in rejects] == [2]
    assert rejects[0].reason == "NONPOSITIVE"


def test_ohlc_logic_violation_rejected():
    rows = _clean_rows()
    # high (5290) below low (5310) — impossible
    rows[1] = _row("2026-05-07T10:00:00", 5300.0, 5290.0, 5310.0, 5305.0)
    rejects = screen_bars(rows)
    assert rejects[0].reason == "OHLC_LOGIC"
    assert rejects[0].index == 1


def test_range_explosion_rejected():
    rows = _clean_rows()
    # low 3000 vs high 5310 → 77% span, an impossible single-bar range
    rows[3] = _row("2026-05-07T12:00:00", 5300.0, 5310.0, 3000.0, 5305.0)
    rejects = screen_bars(rows)
    assert rejects[0].reason == "RANGE_EXPLOSION"


def test_blocked_source_rejected():
    rows = _clean_rows()
    rows[0] = _row("2026-05-07T09:00:00", 5300.0, 5310.0, 5290.0, 5305.0, source="smoke_test")
    rejects = screen_bars(rows)
    assert rejects[0].reason == "BLOCKED_SOURCE"


def test_nonfinite_rejected():
    rows = _clean_rows()
    rows[2] = _row("2026-05-07T11:00:00", 5300.0, float("nan"), 5290.0, 5305.0)
    rejects = screen_bars(rows)
    assert rejects[0].reason == "NONFINITE"


def test_lone_neighbor_jump_rejected():
    # MES "+7489%" fake print: one bar's close ~10x its time-neighbours.
    rows = _clean_rows(5, base=5300.0)
    rows[2] = _row("2026-05-07T11:00:00", 5302.0, 53020.0, 5301.0, 53020.0)
    rejects = screen_bars(rows)
    reasons = {r.reason for r in rejects}
    # range-explosion or neighbour-jump — either way the spike bar (idx 2) dies,
    # and ONLY that bar.
    assert [r.index for r in rejects] == [2]
    assert reasons & {"NEIGHBOR_JUMP", "RANGE_EXPLOSION"}


def test_genuine_persistent_gap_not_rejected():
    # A real overnight gap that CARRIES FORWARD (not a lone spike) must survive,
    # even though it exceeds the jump threshold vs the prior bar.
    rows = [
        _row("2026-05-07T09:00:00", 5300.0, 5310.0, 5295.0, 5305.0),
        _row("2026-05-07T10:00:00", 5305.0, 5315.0, 5300.0, 5308.0),
        # +60% gap up, then it STAYS up — a sustained level, not an outlier
        _row("2026-05-07T11:00:00", 8500.0, 8520.0, 8490.0, 8510.0),
        _row("2026-05-07T12:00:00", 8510.0, 8530.0, 8505.0, 8520.0),
        _row("2026-05-07T13:00:00", 8520.0, 8540.0, 8515.0, 8530.0),
    ]
    assert screen_bars(rows) == []


# ---------------------------------------------------------------------------
# apply_gate — shadow vs enforce semantics
# ---------------------------------------------------------------------------


def test_apply_gate_shadow_keeps_all(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setenv("BAR_QUALITY_GATE_ENFORCE", "0")
    rows = _clean_rows()
    rows[2] = _row("2026-05-07T11:00:00", 0.0, 5310.0, 5290.0, 5305.0)
    kept, rejects = apply_gate(list(rows), symbol="MES", interval="1h")
    assert len(kept) == len(rows)  # shadow: nothing dropped
    assert len(rejects) == 1


def test_apply_gate_enforce_drops_bad(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setenv("BAR_QUALITY_GATE_ENFORCE", "1")
    rows = _clean_rows()
    rows[2] = _row("2026-05-07T11:00:00", 0.0, 5310.0, 5290.0, 5305.0)
    kept, rejects = apply_gate(list(rows), symbol="MES", interval="1h")
    assert len(kept) == len(rows) - 1
    assert len(rejects) == 1


def test_apply_gate_disabled_passthrough(monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "0")
    rows = _clean_rows()
    rows[2] = _row("2026-05-07T11:00:00", 0.0, 5310.0, 5290.0, 5305.0)
    kept, rejects = apply_gate(list(rows), symbol="MES", interval="1h")
    assert len(kept) == len(rows)
    assert rejects == []


# ---------------------------------------------------------------------------
# save_bars integration
# ---------------------------------------------------------------------------


def test_save_bars_enforce_excludes_bad_row(tmp_path, monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setenv("BAR_QUALITY_GATE_ENFORCE", "1")
    db = _make_db(tmp_path)
    df = _bars_df([
        (9, 5300, 5310, 5295, 5305),
        (10, 5305, 5315, 5300, 5308),
        (11, 5302, 5312, 0.0, 5307),     # nonpositive low → rejected
        (12, 5308, 5318, 5303, 5311),
    ])
    saved = save_bars(df, "MES", "1h", "ibkr", db_path=db)
    assert saved == 3  # the bad bar never persisted
    loaded = load_bars("MES", "1h", db_path=db)
    assert len(loaded) == 3
    assert (loaded[["open", "high", "low", "close"]] > 0).all().all()


def test_save_bars_shadow_persists_all(tmp_path, monkeypatch):
    monkeypatch.setenv("BAR_QUALITY_GATE_ENABLED", "1")
    monkeypatch.setenv("BAR_QUALITY_GATE_ENFORCE", "0")
    db = _make_db(tmp_path)
    # Range-explosion bar: (high-low)/low = (9000-5295)/5295 = 0.70 > MAX_RANGE_FRAC,
    # so the quality gate flags it — but it has coherent OHLC and a near-neighbour
    # close, so the hard _row_rejection prefilter in save_bars passes it through.
    # That lets this test exercise the quality gate's SHADOW behavior (log, don't
    # block) without colliding with the unconditional impossible-bar drop. A
    # low=0.0 bar would be hard-dropped by _row_rejection before the gate runs.
    df = _bars_df([
        (9, 5300, 5310, 5295, 5305),
        (10, 5305, 9000, 5295, 5308),   # range explosion: shadow mode writes it anyway
    ])
    saved = save_bars(df, "MES", "1h", "ibkr", db_path=db)
    assert saved == 2  # shadow: logged but not blocked
