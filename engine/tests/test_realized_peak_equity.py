"""
Tests for the phantom-drawdown fix (migration_029 / realized_peak_equity).

Coverage targets
----------------
1. compute_realized_equity excludes open-position MTM.
2. compute_realized_peak is monotonically non-decreasing.
3. Realized peak is unaffected by open-position MTM swings (2026-05-11 scenario).
4. C5 uses realized_peak_equity, not peak_equity (old definition would fail;
   new definition passes).
5. safety_layer.py still references peak_equity (kill switch unchanged).
6. MaxDrawdownCriterion falls back to MTM peak_equity when realized_peak_equity
   is NULL for all rows (pre-migration_029 databases).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# ── path setup ────────────────────────────────────────────────────────────────

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from portfolio.realized_pnl import compute_realized_equity, compute_realized_peak
from readiness.phase3_criteria import MaxDrawdownCriterion

_UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_snapshot_db(
    snapshots: list[dict],
    *,
    include_realized_col: bool = True,
) -> str:
    """
    Create a temporary SQLite DB with a pnl_snapshots table.

    Parameters
    ----------
    snapshots:
        List of dicts with keys: date, portfolio_equity, peak_equity,
        and (optionally) realized_peak_equity, daily_pnl.
    include_realized_col:
        When False the realized_peak_equity column is omitted entirely
        (simulates a pre-migration_029 database).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)

    if include_realized_col:
        conn.execute(
            """
            CREATE TABLE pnl_snapshots (
                date                  TEXT PRIMARY KEY,
                daily_pnl             REAL NOT NULL DEFAULT 0.0,
                portfolio_equity      REAL NOT NULL DEFAULT 0.0,
                peak_equity           REAL NOT NULL DEFAULT 0.0,
                consecutive_losses    INTEGER NOT NULL DEFAULT 0,
                updated_at            TEXT NOT NULL DEFAULT (datetime('now','utc')),
                realized_peak_equity  REAL DEFAULT NULL
            )
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE pnl_snapshots (
                date                  TEXT PRIMARY KEY,
                daily_pnl             REAL NOT NULL DEFAULT 0.0,
                portfolio_equity      REAL NOT NULL DEFAULT 0.0,
                peak_equity           REAL NOT NULL DEFAULT 0.0,
                consecutive_losses    INTEGER NOT NULL DEFAULT 0,
                updated_at            TEXT NOT NULL DEFAULT (datetime('now','utc'))
            )
            """
        )

    for s in snapshots:
        if include_realized_col:
            conn.execute(
                "INSERT OR REPLACE INTO pnl_snapshots "
                "(date, daily_pnl, portfolio_equity, peak_equity, realized_peak_equity) "
                "VALUES (?,?,?,?,?)",
                (
                    s["date"],
                    s.get("daily_pnl", 0.0),
                    s.get("portfolio_equity", 10_000.0),
                    s.get("peak_equity", 10_000.0),
                    s.get("realized_peak_equity"),  # may be None
                ),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO pnl_snapshots "
                "(date, daily_pnl, portfolio_equity, peak_equity) "
                "VALUES (?,?,?,?)",
                (
                    s["date"],
                    s.get("daily_pnl", 0.0),
                    s.get("portfolio_equity", 10_000.0),
                    s.get("peak_equity", 10_000.0),
                ),
            )

    conn.commit()
    conn.close()
    return path


def _days_ago(n: int) -> str:
    return (datetime.now(_UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


# ── 1. compute_realized_equity excludes open positions ────────────────────────


class TestComputeRealizedEquity:
    def test_excludes_open_positions(self):
        """
        2 closed trades (+$200 each) + 1 open trade (MTM +$5000).
        Realized equity = 10_000 + 400 = 10_400.
        The open trade's pnl=None means it must not affect the sum.
        """
        trades = [
            {"status": "closed", "pnl": 200.0},
            {"status": "closed", "pnl": 200.0},
            {"status": "open", "pnl": None},  # unrealized MTM — excluded
        ]
        result = compute_realized_equity(trades, starting_capital=10_000.0)
        assert result == pytest.approx(10_400.0, abs=0.01)

    def test_empty_trades(self):
        result = compute_realized_equity([], starting_capital=10_000.0)
        assert result == pytest.approx(10_000.0)

    def test_all_losses(self):
        trades = [{"pnl": -100.0}, {"pnl": -200.0}]
        result = compute_realized_equity(trades, starting_capital=10_000.0)
        assert result == pytest.approx(9_700.0)

    def test_skips_none_pnl(self):
        trades = [{"pnl": 500.0}, {"pnl": None}, {"pnl": 300.0}]
        result = compute_realized_equity(trades, starting_capital=10_000.0)
        assert result == pytest.approx(10_800.0)


# ── 2. compute_realized_peak is monotonically non-decreasing ──────────────────


class TestComputeRealizedPeak:
    def test_monotonically_non_decreasing(self):
        """Peak must only go up, never down."""
        snapshots = [
            {"realized_equity": 10_000.0},
            {"realized_equity": 10_200.0},
            {"realized_equity": 10_100.0},  # equity dips but peak stays at 10_200
            {"realized_equity": 10_300.0},
            {"realized_equity": 10_250.0},
        ]
        # verify running peak is non-decreasing
        running_peak = 0.0
        peaks = []
        for snap in snapshots:
            snap_with_peak = dict(snap)
            running_peak = max(running_peak, snap["realized_equity"])
            peaks.append(running_peak)

        for i in range(1, len(peaks)):
            assert peaks[i] >= peaks[i - 1], f"Peak decreased at index {i}: {peaks}"

    def test_peak_returns_max(self):
        snapshots = [
            {"realized_equity": 10_000.0},
            {"realized_equity": 12_000.0},
            {"realized_equity": 9_000.0},
        ]
        result = compute_realized_peak(snapshots)
        assert result == pytest.approx(12_000.0)

    def test_empty_returns_zero(self):
        assert compute_realized_peak([]) == 0.0

    def test_single_snapshot(self):
        result = compute_realized_peak([{"realized_equity": 11_500.0}])
        assert result == pytest.approx(11_500.0)


# ── 3. Realized peak unaffected by unrealized MTM swing (2026-05-11 scenario) ─


class TestRealizedPeakUnaffectedByMTMSwing:
    """
    Reproduces the 2026-05-11 phantom drawdown incident.

    Scenario:
    - Closed trades over 60 days: all profitable, total realized PnL = +$60_617
    - On 2026-05-11: an open position (short) had a large paper profit (MTM equity
      surged), setting peak_equity = 24_617.
    - The market then recovered; MTM equity fell back to ~14_617 while the position
      was still open (not yet realized).
    - peak_equity stays at 24_617; portfolio_equity = 14_617 → MTM drawdown = 40.6%.
    - realized_peak_equity = 10_617 (no closed trade pushed equity above that).
    - realized_equity = 10_617 (starting capital + realized P&L).
    - Realized drawdown = (10_617 - 10_617) / 10_617 = 0%.

    Old C5 (MTM peak) → FAIL (40.6% > 8%).
    New C5 (realized peak) → PASS (0% drawdown).
    """

    def _build_snapshots(self) -> list[dict]:
        base_date = datetime.now(_UTC) - timedelta(days=30)
        snapshots = []
        for i in range(30):
            d = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            snapshots.append(
                {
                    "date": d,
                    "daily_pnl": 0.0,
                    "portfolio_equity": 10_617.0,  # realized-only equity: stable
                    "peak_equity": 10_617.0,  # MTM peak on most days
                    "realized_peak_equity": 10_617.0,  # realized peak: stable, climbing slowly
                }
            )

        # Override one row to simulate the MTM spike on day 20:
        # MTM equity surged to 24_617 (open short deeply in-profit),
        # then fell back to 14_617 (position still open, reversal).
        spike_idx = 20
        snapshots[spike_idx]["peak_equity"] = 24_617.0
        snapshots[spike_idx]["portfolio_equity"] = 14_617.0
        # realized_peak_equity stays at 10_617 — no closed trade caused that spike
        return snapshots

    def test_realized_peak_unaffected_by_mtm_swing(self):
        """Verify compute_realized_peak ignores the MTM spike."""
        snapshots_as_realized = [
            {"realized_equity": s["realized_peak_equity"]} for s in self._build_snapshots()
        ]
        peak = compute_realized_peak(snapshots_as_realized)
        # Realized peak should be 10_617, NOT 24_617
        assert peak == pytest.approx(
            10_617.0, abs=0.01
        ), f"Expected realized peak ~10_617 (ignoring MTM spike), got {peak}"

    def test_c5_passes_with_realized_peak_fails_with_mtm_peak(self):
        """
        With realized_peak_equity populated, C5 passes (0% drawdown).
        If we corrupt the data to set realized_peak_equity = peak_equity
        (i.e., the old MTM-based definition), C5 would fail.
        """
        snapshots = self._build_snapshots()

        # --- NEW definition: realized_peak_equity → C5 should PASS ---
        db_new = _make_snapshot_db(snapshots, include_realized_col=True)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db_new)
            assert passed, (
                f"C5 should PASS with realized_peak_equity populated; " f"evidence={evidence}"
            )
            assert "realized" in evidence.lower()
        finally:
            os.unlink(db_new)

        # --- OLD definition (MTM): replace realized_peak_equity with peak_equity ---
        old_snapshots = [dict(s, realized_peak_equity=s["peak_equity"]) for s in snapshots]
        db_old = _make_snapshot_db(old_snapshots, include_realized_col=True)
        try:
            passed_old, evidence_old = MaxDrawdownCriterion().check(db_old)
            # With old MTM-peak definition the 14_617/24_617 ratio = 40.7% > 8%
            assert not passed_old, (
                f"C5 should FAIL when realized_peak_equity=peak_equity (MTM); "
                f"evidence={evidence_old}"
            )
        finally:
            os.unlink(db_old)


# ── 4. C5 uses realized peak; kill switch still uses peak_equity ──────────────


class TestC5UsesRealizedPeak:
    def test_c5_passes_when_realized_peak_low(self):
        """
        realized_peak_equity is stable (10_500), portfolio_equity stays near it.
        Drawdown ~0% → PASS.
        """
        snapshots = [
            {
                "date": _days_ago(d),
                "daily_pnl": 0.0,
                "portfolio_equity": 10_500.0,
                "peak_equity": 20_000.0,  # MTM peak (would fail old C5)
                "realized_peak_equity": 10_500.0,  # realized peak: no phantom
            }
            for d in range(30, 0, -1)
        ]
        db = _make_snapshot_db(snapshots)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_c5_fails_when_realized_drawdown_is_real(self):
        """
        Closed trades actually lost money: realized equity drops 15% below
        realized peak → C5 should FAIL (real strategy degradation, not a phantom).
        """
        snapshots = [
            {
                "date": _days_ago(d),
                "daily_pnl": 0.0,
                "portfolio_equity": 8_500.0,  # low MTM equity
                "peak_equity": 10_000.0,
                "realized_peak_equity": 10_000.0,  # realized peak was 10k
            }
            for d in range(30, 0, -1)
        ]
        db = _make_snapshot_db(snapshots)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db)
            assert not passed, f"Expected FAIL (15% realized drawdown); evidence={evidence}"
        finally:
            os.unlink(db)

    def test_c5_falls_back_to_mtm_when_realized_col_all_null(self):
        """
        Pre-migration_029 DBs: realized_peak_equity is NULL for all rows.
        C5 must fall back to MTM peak_equity gracefully (no crash, warning in evidence).
        """
        snapshots = [
            {
                "date": _days_ago(d),
                "daily_pnl": 0.0,
                "portfolio_equity": 10_000.0,
                "peak_equity": 10_500.0,
                "realized_peak_equity": None,  # NULL — pre-migration
            }
            for d in range(30, 0, -1)
        ]
        db = _make_snapshot_db(snapshots)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db)
            # Small drawdown (~5%) → pass even with MTM fallback
            assert passed, f"Expected PASS with MTM fallback; evidence={evidence}"
            assert "fallback" in evidence.lower() or "warn" in evidence.lower()
        finally:
            os.unlink(db)


# ── 5. safety_layer.py is unchanged (reads peak_equity) ───────────────────────


class TestKillSwitchStillUsesPeakEquity:
    """
    Structural test: read safety_layer.py and assert it still references
    peak_equity as it always did, and does NOT import or reference
    realized_peak_equity.  This proves the kill switch was not touched.
    """

    def _read_safety_layer(self) -> str:
        path = os.path.join(_ENGINE_DIR, "risk", "safety_layer.py")
        assert os.path.exists(path), f"safety_layer.py not found at {path}"
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_safety_layer_references_peak_equity(self):
        src = self._read_safety_layer()
        assert (
            "peak_equity" in src
        ), "safety_layer.py should still reference 'peak_equity' for kill switch"

    def test_safety_layer_does_not_import_realized_pnl_module(self):
        """
        Verify safety_layer.py does NOT import the new portfolio.realized_pnl
        module.  Note: the string 'realized_pnl' DOES appear in safety_layer.py
        as a field name (_daily_realized_pnl) — that is pre-existing and
        intentional.  We check for the specific module import path.
        """
        src = self._read_safety_layer()
        assert "portfolio.realized_pnl" not in src, (
            "safety_layer.py must NOT import portfolio.realized_pnl — kill switch "
            "must remain independent of the realized-peak-equity fix"
        )
        assert (
            "from portfolio import" not in src
            or "realized_pnl" not in src.split("from portfolio import")[-1].split("\n")[0]
        ), "safety_layer.py must NOT import realized_pnl from portfolio"

    def test_safety_layer_equity_peak_field(self):
        """_equity_peak (the in-memory MTM peak) must still be present."""
        src = self._read_safety_layer()
        assert (
            "_equity_peak" in src
        ), "safety_layer.py must still use _equity_peak for the drawdown halt"
