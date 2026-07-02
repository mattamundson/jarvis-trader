"""Kill-switch min-trade gate (Amo policy, 2026-07-02).

The USD flat daily-loss gate used to latch the moment daily REALIZED P&L
breached -MAX_DAILY_LOSS_USD. On 2026-07-01 a single PHANTOM -$266 closed
trade latched it and halted trading for the day on data that wasn't real.

Since a real single trade is already capped at MAX_TRADE_LOSS_USD ($50/ticket),
a lone breach of the daily flat limit is almost always a phantom/data error.
Policy: the flat USD gate latches only when >=2 realized trades closed today.
The PCT gate (on TOTAL P&L incl. open MTM) is intentionally UNCHANGED.
Fail-safe: if the trade count can't be determined (no db), latch as before.
"""

from __future__ import annotations

import os
import sys
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

from risk.safety_layer import KillSwitchReason, SafetyLayer  # noqa: E402


def _safety(mock_settings, *, count, usd=1000.0, pct=0.08):
    """SafetyLayer whose db reports `count` closed trades today (None = no db)."""
    mock_settings.MAX_DAILY_LOSS_USD = usd
    mock_settings.MAX_DAILY_LOSS_PCT = pct
    if count is None:
        db = None
    else:
        db = MagicMock()
        db.get_pnl_snapshot = MagicMock(return_value=None)  # keep __init__ inert
        db.count_closed_trades_on_date = MagicMock(return_value=count)
    return SafetyLayer(mock_settings, db_manager=db)


class TestFlatGateMinTrades:
    def test_single_trade_does_not_latch(self, mock_settings):
        """One realized trade breaching the flat limit → treated as phantom, no halt."""
        s = _safety(mock_settings, count=1)
        s._daily_realized_pnl = -1500.0  # breaches $1000 flat; within 8% of $100k
        res = s._check_daily_loss_limit(100_000.0)
        assert res.approved is True
        assert s.is_killed is False

    def test_two_trades_latch(self, mock_settings):
        """Two realized trades breaching the flat limit → real, halt."""
        s = _safety(mock_settings, count=2)
        s._daily_realized_pnl = -1500.0
        res = s._check_daily_loss_limit(100_000.0)
        assert res.approved is False
        assert s.is_killed is True
        assert s._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_no_db_fails_safe_and_latches(self, mock_settings):
        """Unknown trade count (no db_manager) → fail safe, preserve old latch."""
        s = _safety(mock_settings, count=None)
        s._daily_realized_pnl = -1500.0
        res = s._check_daily_loss_limit(100_000.0)
        assert res.approved is False
        assert s.is_killed is True

    def test_pct_gate_unaffected_by_trade_count(self, mock_settings):
        """A catastrophic single-trade TOTAL P&L still latches via the PCT gate —
        the min-trade guard only relaxes the flat USD gate."""
        s = _safety(mock_settings, count=1)
        s._daily_realized_pnl = -9000.0  # -9% of $100k > 8% pct limit
        res = s._check_daily_loss_limit(100_000.0)
        assert res.approved is False
        assert s.is_killed is True

    def test_single_trade_within_flat_limit_no_halt(self, mock_settings):
        """Sanity: a single small loss within the flat limit never halts."""
        s = _safety(mock_settings, count=1)
        s._daily_realized_pnl = -200.0
        res = s._check_daily_loss_limit(100_000.0)
        assert res.approved is True
        assert s.is_killed is False


class TestCountClosedTradesOnDate:
    """The DB count method the gate relies on."""

    def test_counts_only_closed_trades_on_date(self, tmp_path):
        import sqlite3

        from database.schema import DatabaseManager

        path = str(tmp_path / "count.db")
        db = DatabaseManager(db_path=path)
        db.initialize()

        def _ins(tid, exit_time, status="closed"):
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    """INSERT INTO paper_trades
                       (trade_id, symbol, side, quantity, entry_price, exit_price,
                        entry_time, exit_time, pnl, status, idempotency_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        tid,
                        "MES",
                        "buy",
                        1,
                        100.0,
                        101.0,
                        exit_time,
                        exit_time,
                        10.0,
                        status,
                        f"i-{tid}",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        _ins("a", "2026-07-02 14:00:00")
        _ins("b", "2026-07-02 15:00:00")
        _ins("c", "2026-07-01 15:00:00")  # different day
        _ins("d", "2026-07-02 16:00:00", status="phantom")  # not closed

        assert db.count_closed_trades_on_date("2026-07-02") == 2
        assert db.count_closed_trades_on_date("2026-07-01") == 1
        assert db.count_closed_trades_on_date("2026-06-30") == 0
