"""Regression cover for outcome_hygiene -- the single source of truth that keeps
fabricated and duplicate P&L rows out of every calibration/P&L read path.

This locks in the anti-fabrication guards behind the honest-P&L work (the
+$10,102.98 phantom and the triplicate-row artifact). Mutation checks:
  * remove the `if key in seen: continue` dedup -> duplicate cases go red
  * remove the `abs(pnl) > MAX_PLAUSIBLE_ABS_PNL_USD` guard -> corrupt cases red
"""

from __future__ import annotations

import sqlite3

import pytest

from analytics.outcome_hygiene import (
    MAX_PLAUSIBLE_ABS_PNL_USD,
    is_plausible_pnl,
    sanitize_outcome_rows,
    window_integrity,
)

BOUND = MAX_PLAUSIBLE_ABS_PNL_USD


# --- is_plausible_pnl -------------------------------------------------------

@pytest.mark.parametrize(
    "pnl,expected",
    [
        (None, True),          # legacy row, no magnitude to reject
        (0.0, True),
        (100.0, True),
        (-100.0, True),
        (BOUND, True),         # boundary is inclusive (<=)
        (BOUND + 0.01, False),
        (10102.98, False),     # the documented phantom
        (-10102.98, False),
    ],
)
def test_is_plausible_pnl(pnl, expected):
    assert is_plausible_pnl(pnl) is expected


# --- sanitize_outcome_rows (default (signal, pnl, ts) shape) ----------------

def test_sanitize_drops_corrupt_and_duplicates_keeps_distinct():
    r1 = (0.8, 100.0, "2026-06-01T10:00:00")            # keep
    r2 = (0.8, 100.0, "2026-06-01T10:00:00")            # exact dup -> drop
    r3 = (0.8, 100.0, "2026-06-01T10:00:00.500")        # same second -> dup -> drop
    r4 = (0.8, 100.0, "2026-06-01T10:00:01")            # next second -> distinct keep
    r5 = (0.5, 10102.98, "2026-06-01T11:00:00")         # corrupt magnitude -> drop
    r6 = (None, 50.0, "2026-06-01T12:00:00")            # None signal -> skipped
    r7 = (0.3, None, "2026-06-01T13:00:00")             # None pnl -> plausible keep

    cleaned, n_corrupt, n_dup = sanitize_outcome_rows(
        [r1, r2, r3, r4, r5, r6, r7], context="test", return_counts=True
    )

    assert cleaned == [r1, r4, r7]
    assert n_corrupt == 1
    assert n_dup == 2


def test_sanitize_without_counts_returns_only_cleaned():
    rows = [(0.8, 100.0, "2026-06-01T10:00:00"), (0.8, 100.0, "2026-06-01T10:00:00")]
    cleaned = sanitize_outcome_rows(rows, context="test")
    assert cleaned == [rows[0]]


def test_sanitize_distinct_pnl_same_second_not_collapsed():
    # Same second + same signal but DIFFERENT pnl must NOT be treated as a dup.
    a = (0.8, 100.0, "2026-06-01T10:00:00")
    b = (0.8, 150.0, "2026-06-01T10:00:00")
    cleaned = sanitize_outcome_rows([a, b], context="test")
    assert cleaned == [a, b]


def test_sanitize_supports_alternate_column_indices():
    # The (direction, outcome, signal, ts, pnl) directional-accuracy shape.
    a = ("long", "win", 0.7, "2026-06-01T10:00:00", 200.0)
    dup = ("long", "win", 0.7, "2026-06-01T10:00:00", 200.0)
    cleaned, n_corrupt, n_dup = sanitize_outcome_rows(
        [a, dup], context="dir", signal_idx=2, pnl_idx=4, ts_idx=3, return_counts=True
    )
    assert cleaned == [a]
    assert (n_corrupt, n_dup) == (0, 1)


# --- window_integrity -------------------------------------------------------

def _seed_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE trade_outcomes (symbol TEXT, timestamp TEXT, pnl_usd REAL)"
    )
    conn.executemany(
        "INSERT INTO trade_outcomes (symbol, timestamp, pnl_usd) VALUES (?,?,?)",
        [
            ("MES", "2026-06-01T10:00:00", 100.0),     # keep
            ("MES", "2026-06-01T10:00:00", 100.0),     # dup
            ("MES", "2026-06-01T11:00:00", 10102.98),  # corrupt
            ("MGC", "2026-06-01T12:00:00", 50.0),      # distinct
            ("MES", "2026-05-01T09:00:00", 100.0),     # before cutoff -> ignored
        ],
    )
    conn.commit()
    return conn


def test_window_integrity_counts_corrupt_and_duplicate():
    conn = _seed_db()
    try:
        n_corrupt, n_dup = window_integrity(conn, "2026-06-01T00:00:00")
        assert n_corrupt == 1
        assert n_dup == 1
    finally:
        conn.close()


def test_window_integrity_best_effort_on_missing_table():
    conn = sqlite3.connect(":memory:")
    try:
        assert window_integrity(conn, "2026-06-01T00:00:00") == (0, 0)
    finally:
        conn.close()
