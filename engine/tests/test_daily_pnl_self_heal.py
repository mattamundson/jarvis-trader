"""Self-heal (corrective) daily_pnl regression tests (2026-07-02).

Companion to test_daily_pnl_integrity.py. Where that suite covers the write
GUARD (refuse bad rows) and the EOD writer's anchoring, this suite covers the
CORRECTIVE control: DailyPnLMixin.repair_daily_pnl rebuilds the whole table from
the closed paper_trades ledger using the same absolute-anchoring formula the EOD
writer uses (initial_capital + cumulative status='closed' P&L per UTC date).

Motivating case: a phantom trade is booked status='closed', counted by the EOD
snapshot, and only reclassified to status='phantom' days later (manual
mark_phantom_trades.py). The stored daily_pnl row is now wrong. reconcile_daily_pnl
(detective) FLAGS the drift; repair_daily_pnl (corrective) HEALS it so the table
self-corrects on the next cycle without touching the kill-switch.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

INITIAL = 10_000.0


@pytest.fixture()
def dbp(tmp_path):
    """Return (DatabaseManager, db_path) so tests can INSERT ledger rows directly."""
    from database.schema import DatabaseManager

    path = str(tmp_path / "self_heal.db")
    manager = DatabaseManager(db_path=path)
    manager.initialize()
    return manager, path


def _insert_closed_trade(path, *, trade_id, symbol, exit_time, pnl, status="closed"):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO paper_trades
               (trade_id, symbol, side, quantity, entry_price, exit_price,
                entry_time, exit_time, pnl, status, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade_id,
                symbol,
                "buy",
                1,
                100.0,
                101.0,
                exit_time,
                exit_time,
                pnl,
                status,
                f"idem-{trade_id}",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_daily_pnl(path, *, date, starting, ending, realized, total_trades):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO daily_pnl (date, starting_balance, ending_balance,
                realized_pnl, unrealized_pnl, total_trades, winning_trades,
                losing_trades, max_drawdown)
               VALUES (?,?,?,?,0,?,0,0,0)""",
            (date, starting, ending, realized, total_trades),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_ledger(path):
    """3 real closed trades: +100, -30, +50 across three UTC dates. Net +120."""
    _insert_closed_trade(
        path, trade_id="t1", symbol="MES", exit_time="2026-06-20 15:00:00", pnl=100.0
    )
    _insert_closed_trade(
        path, trade_id="t2", symbol="MES", exit_time="2026-06-21 15:00:00", pnl=-30.0
    )
    _insert_closed_trade(
        path, trade_id="t3", symbol="MES", exit_time="2026-06-22 15:00:00", pnl=50.0
    )


class TestRepairDailyPnl:
    def test_dry_run_writes_nothing(self, dbp):
        db, path = dbp
        _seed_ledger(path)
        # A corrupt stored row (counts a phantom: +500 vs real +100) and an orphan.
        _insert_daily_pnl(
            path,
            date="2026-06-20",
            starting=INITIAL,
            ending=10_500.0,
            realized=500.0,
            total_trades=2,
        )
        _insert_daily_pnl(
            path, date="2026-06-19", starting=INITIAL, ending=INITIAL, realized=0.0, total_trades=0
        )

        res = db.repair_daily_pnl(initial_capital=INITIAL, dry_run=True)
        assert res["applied"] is False
        assert res["rows_changed"] >= 1
        # DB untouched: reconcile still sees drift on 2026-06-20.
        rec = db.reconcile_daily_pnl()
        assert rec["ok"] is False

    def test_repair_rebuilds_and_reconciles_clean(self, dbp):
        db, path = dbp
        _seed_ledger(path)
        _insert_daily_pnl(
            path,
            date="2026-06-20",
            starting=INITIAL,
            ending=10_500.0,
            realized=500.0,
            total_trades=2,
        )
        _insert_daily_pnl(
            path, date="2026-06-19", starting=INITIAL, ending=INITIAL, realized=0.0, total_trades=0
        )  # orphan

        res = db.repair_daily_pnl(initial_capital=INITIAL, dry_run=False)
        assert res["applied"] is True
        assert res["orphans_removed"] == 1  # 2026-06-19 (no closed trades) dropped
        assert res["final_ending"] == pytest.approx(10_120.0)  # 10000 + 120
        assert res["total_realized"] == pytest.approx(120.0)

        rows = {r["date"]: r for r in db.get_daily_pnl()}
        assert set(rows) == {"2026-06-20", "2026-06-21", "2026-06-22"}
        # Chained, identity-clean balances.
        assert rows["2026-06-20"]["starting_balance"] == pytest.approx(10_000.0)
        assert rows["2026-06-20"]["ending_balance"] == pytest.approx(10_100.0)
        assert rows["2026-06-21"]["starting_balance"] == pytest.approx(10_100.0)
        assert rows["2026-06-22"]["ending_balance"] == pytest.approx(10_120.0)
        for r in rows.values():
            assert r["starting_balance"] + r["realized_pnl"] == pytest.approx(r["ending_balance"])
        # Detective control now clean.
        assert db.reconcile_daily_pnl()["ok"] is True

    def test_repair_excludes_phantom_status(self, dbp):
        db, path = dbp
        _seed_ledger(path)
        # A phantom booked closed then reclassified: must NOT count in the rebuild.
        _insert_closed_trade(
            path,
            trade_id="tp",
            symbol="MES",
            exit_time="2026-06-22 16:00:00",
            pnl=-266.25,
            status="phantom",
        )
        res = db.repair_daily_pnl(initial_capital=INITIAL, dry_run=False)
        assert res["final_ending"] == pytest.approx(10_120.0)  # phantom -266.25 excluded
        rows = {r["date"]: r for r in db.get_daily_pnl()}
        assert rows["2026-06-22"]["realized_pnl"] == pytest.approx(50.0)  # not 50 - 266.25

    def test_repair_idempotent(self, dbp):
        db, path = dbp
        _seed_ledger(path)
        db.repair_daily_pnl(initial_capital=INITIAL, dry_run=False)
        second = db.repair_daily_pnl(initial_capital=INITIAL, dry_run=False)
        assert second["rows_changed"] == 0
        assert second["orphans_removed"] == 0


class TestEodSelfHealWiring:
    """run_eod_snapshot runs the corrective control on real data: a phantom
    reclassified since the last EOD leaves a drifted historical row, and the
    next EOD self-heals it."""

    @pytest.mark.asyncio
    async def test_eod_heals_reclassified_phantom_drift(self, dbp):
        db, path = dbp

        # CT (UTC-6) today, matching EODScheduler._today_date_str.
        ct_now = datetime.now(timezone.utc) - timedelta(hours=6)
        today = ct_now.strftime("%Y-%m-%d")

        # A real historical closed trade (+100) and a real trade today (+40) so
        # today's EOD row is ledger-backed and survives the rebuild.
        _insert_closed_trade(
            path, trade_id="h1", symbol="MES", exit_time="2026-06-20 15:00:00", pnl=100.0
        )
        _insert_closed_trade(
            path, trade_id="d1", symbol="MES", exit_time=f"{today} 15:00:00", pnl=40.0
        )
        # The phantom that was booked closed, counted, then reclassified: the
        # historical daily_pnl row still reflects the inflated +500 realized.
        _insert_daily_pnl(
            path,
            date="2026-06-20",
            starting=INITIAL,
            ending=10_500.0,
            realized=500.0,
            total_trades=2,
        )

        # Pre-check: detective control sees the drift.
        assert db.reconcile_daily_pnl()["ok"] is False

        from schedulers.eod_scheduler import EODScheduler

        tracker = MagicMock()
        tracker.get_performance = MagicMock(
            return_value={"total_pnl": 140.0, "num_trades": 2, "win_rate": 1.0, "max_dd": -0.01}
        )
        tracker.get_positions = MagicMock(return_value=[])
        scheduler = EODScheduler(db_manager=db, portfolio_tracker=tracker)

        snapshot = await scheduler.run_eod_snapshot()

        # The EOD self-heal fired and the table is clean again.
        assert snapshot.get("self_heal", {}).get("applied") is True
        assert db.reconcile_daily_pnl()["ok"] is True
        rows = {r["date"]: r for r in db.get_daily_pnl()}
        assert rows["2026-06-20"]["realized_pnl"] == pytest.approx(100.0)  # healed from 500
        assert rows["2026-06-20"]["ending_balance"] == pytest.approx(10_100.0)
