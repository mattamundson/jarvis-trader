"""
daily_pnl integrity regression tests (2026-06-12 corruption fix).

The daily_pnl table was corrupted by writers with mismatched balance bases:
a $10k-anchored EOD writer chained starting_balance off whatever the previous
row said, so one basis-flipped row (e.g. a ~$50k monitor-state balance)
manufactured phantom ±$40k "realized" days in both directions, plus stale
rows where ending != starting + realized.

Two defenses under test here:
1. DailyPnLMixin write guard — refuses implausible snapshots at the DB layer.
2. EODScheduler paper_trades anchoring — balances derive from initial capital
   + cumulative CLOSED round-trip P&L, never from the previous daily_pnl row.
"""

from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# Layer 1 — DailyPnLMixin write guard
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    from database.schema import DatabaseManager

    manager = DatabaseManager(db_path=str(tmp_path / "guard_test.db"))
    manager.initialize()
    return manager


class TestDailyPnlWriteGuard:
    def test_refuses_basis_flip_realized(self, db):
        """The 2026-06-02 corruption row: +$39,842 'realized' on a $10k book."""
        written = db.upsert_daily_pnl(
            date="2026-06-02",
            starting_balance=10_000.0,
            ending_balance=49_842.002,
            realized_pnl=39_842.002,
            unrealized_pnl=0.0,
            total_trades=56,
            winning_trades=14,
            losing_trades=42,
            max_drawdown=-42_083.384,
        )
        assert written is False
        assert db.get_daily_pnl(start_date="2026-06-02", end_date="2026-06-02") == []

    def test_refuses_balance_identity_violation(self, db):
        """The stale 2026-05 rows: ending != starting + realized."""
        written = db.upsert_daily_pnl(
            date="2026-05-05",
            starting_balance=10_330.0,
            ending_balance=10_330.0,
            realized_pnl=180.0,  # 10330 + 180 != 10330
            unrealized_pnl=0.0,
            total_trades=31,
            winning_trades=4,
            losing_trades=27,
            max_drawdown=0.0,
        )
        assert written is False

    def test_refuses_nonpositive_balances(self, db):
        written = db.upsert_daily_pnl(
            date="2026-06-03",
            starting_balance=0.0,
            ending_balance=-50.0,
            realized_pnl=-50.0,
            unrealized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            losing_trades=1,
            max_drawdown=-50.0,
        )
        assert written is False

    def test_accepts_sane_snapshot(self, db):
        written = db.upsert_daily_pnl(
            date="2026-06-11",
            starting_balance=8_273.116,
            ending_balance=8_118.2965,
            realized_pnl=-154.8195,
            unrealized_pnl=0.0,
            total_trades=2,
            winning_trades=1,
            losing_trades=1,
            max_drawdown=-160.0,
        )
        assert written is True
        rows = db.get_daily_pnl(start_date="2026-06-11", end_date="2026-06-11")
        assert len(rows) == 1
        assert rows[0]["realized_pnl"] == pytest.approx(-154.8195)


# ---------------------------------------------------------------------------
# Layer 2 — EODScheduler anchors balances to closed paper_trades
# ---------------------------------------------------------------------------


def _ct_today_and_yesterday() -> tuple[str, str]:
    """Mirror EODScheduler._today_date_str (UTC-6)."""
    ct_now = datetime.now(timezone.utc) - timedelta(hours=6)
    return ct_now.strftime("%Y-%m-%d"), (ct_now - timedelta(days=1)).strftime("%Y-%m-%d")


def _make_scheduler(closed_trades):
    from schedulers.eod_scheduler import EODScheduler

    mock_db = MagicMock()
    mock_db.get_trade_history = MagicMock(return_value=closed_trades)
    mock_db.upsert_daily_pnl = MagicMock(return_value=True)

    mock_tracker = MagicMock()
    mock_tracker.get_performance = MagicMock(
        return_value={"total_pnl": 999_999.0, "num_trades": 999, "win_rate": 0.5, "max_dd": -0.02}
    )
    mock_tracker.get_positions = MagicMock(return_value=[])

    return EODScheduler(db_manager=mock_db, portfolio_tracker=mock_tracker), mock_db


class TestEodSnapshotPaperTradesAnchoring:
    @pytest.mark.asyncio
    async def test_balances_derive_from_closed_round_trips(self):
        """starting/ending come from 10k + cumulative closed P&L, NOT from
        tracker lifetime aggregates (poisoned to 999,999 here on purpose) and
        NOT from any previous daily_pnl row."""
        today, yesterday = _ct_today_and_yesterday()
        closed = [
            {"exit_time": f"{yesterday}T15:00:00+00:00", "pnl": 500.0},
            {"exit_time": f"{today}T14:00:00+00:00", "pnl": -150.0},
            {"exit_time": f"{today}T15:30:00+00:00", "pnl": 50.0},
        ]
        scheduler, mock_db = _make_scheduler(closed)
        snapshot = await scheduler.run_eod_snapshot()

        assert snapshot["starting_balance"] == pytest.approx(10_500.0)
        assert snapshot["ending_balance"] == pytest.approx(10_400.0)
        assert snapshot["realized_pnl"] == pytest.approx(-100.0)
        assert snapshot["total_trades"] == 2  # today's round-trips only
        assert snapshot["winning_trades"] == 1
        assert snapshot["losing_trades"] == 1
        assert snapshot["status"] == "ok"

        kwargs = mock_db.upsert_daily_pnl.call_args[1]
        assert kwargs["starting_balance"] == pytest.approx(10_500.0)
        assert kwargs["ending_balance"] == pytest.approx(10_400.0)
        # The written row always satisfies the guard's balance identity.
        assert kwargs["starting_balance"] + kwargs["realized_pnl"] == pytest.approx(
            kwargs["ending_balance"]
        )

    @pytest.mark.asyncio
    async def test_refused_write_surfaces_in_status(self):
        today, _ = _ct_today_and_yesterday()
        closed = [{"exit_time": f"{today}T14:00:00+00:00", "pnl": 25.0}]
        scheduler, mock_db = _make_scheduler(closed)
        mock_db.upsert_daily_pnl = MagicMock(return_value=False)

        snapshot = await scheduler.run_eod_snapshot()
        assert snapshot["status"] == "refused"

    def test_today_summary_uses_same_anchor(self):
        today, yesterday = _ct_today_and_yesterday()
        closed = [
            {"exit_time": f"{yesterday}T15:00:00+00:00", "pnl": 1_291.30},
            {"exit_time": f"{today}T14:00:00+00:00", "pnl": 100.0},
        ]
        scheduler, _ = _make_scheduler(closed)
        summary = scheduler.get_today_summary()

        assert summary["starting_balance"] == pytest.approx(11_291.30)
        assert summary["ending_balance"] == pytest.approx(11_391.30)
        assert summary["realized_pnl"] == pytest.approx(100.0)
        assert summary["total_trades"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_tracker_when_no_db(self):
        """Without a DB the legacy lifetime-anchor path still produces a snapshot."""
        from schedulers.eod_scheduler import EODScheduler

        mock_tracker = MagicMock()
        mock_tracker.get_performance = MagicMock(
            return_value={"total_pnl": 250.0, "num_trades": 3, "win_rate": 2 / 3, "max_dd": -0.01}
        )
        mock_tracker.get_positions = MagicMock(return_value=[])

        scheduler = EODScheduler(db_manager=None, portfolio_tracker=mock_tracker)
        snapshot = await scheduler.run_eod_snapshot()
        assert snapshot["ending_balance"] == pytest.approx(10_250.0)
        assert snapshot["status"] == "no_db"
