"""
Regression test for ``get_stats_summary`` trade-level derived metrics.

Bug (2026-06-16): ``DatabaseManager.get_stats_summary`` computed trade counts
+ ``total_pnl`` and the day-level best/worst, but never produced ``win_rate``,
``avg_win``, ``avg_loss``, ``profit_factor``, ``best_trade`` or
``worst_trade``. The ``/portfolio/stats/summary`` response model
(``StatsSummaryResponse``) declares those fields, so they silently defaulted
to 0.0 on the live endpoint -- e.g. a 0% win rate / 0 profit factor displayed
over 19 real closed trades. These tests pin the derived metrics and the
divide-by-zero guards.
"""

from __future__ import annotations

import os
import sqlite3
import sys

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


@pytest.fixture()
def db(tmp_path):
    from database.schema import DatabaseManager

    manager = DatabaseManager(db_path=str(tmp_path / "stats_summary_test.db"))
    manager.initialize()
    return manager


def _insert_trade(db, trade_id, pnl, status="closed", symbol="MES"):
    """Insert a single paper_trades row with an explicit pnl (NULL while open)."""
    conn = sqlite3.connect(str(db._db_path))
    try:
        conn.execute(
            """INSERT INTO paper_trades
               (trade_id, symbol, side, quantity, entry_price, exit_price,
                entry_time, exit_time, pnl, status, idempotency_key)
               VALUES (?, ?, 'buy', 1.0, 100.0, 101.0,
                       '2026-06-16T00:00:00+00:00', '2026-06-16T01:00:00+00:00',
                       ?, ?, ?)""",
            (trade_id, symbol, pnl, status, f"idem-{trade_id}"),
        )
        conn.commit()
    finally:
        conn.close()


class TestStatsSummaryDerivedMetrics:
    def test_empty_db_is_all_zero_no_div_by_zero(self, db):
        s = db.get_stats_summary()
        assert s["total_trades"] == 0
        assert s["win_rate"] == 0.0
        assert s["profit_factor"] == 0.0
        assert s["avg_win"] == 0.0
        assert s["avg_loss"] == 0.0
        assert s["best_trade"] == 0.0
        assert s["worst_trade"] == 0.0

    def test_derived_metrics_computed(self, db):
        # 3 wins (+100, +200, +300), 2 losses (-50, -150), 1 breakeven (0)
        for i, pnl in enumerate([100.0, 200.0, 300.0, -50.0, -150.0, 0.0]):
            _insert_trade(db, f"t{i}", pnl)
        # an OPEN trade (pnl NULL) must be excluded from every aggregate
        _insert_trade(db, "open1", None, status="open")

        s = db.get_stats_summary()
        assert s["total_trades"] == 6
        assert s["winning_trades"] == 3
        assert s["losing_trades"] == 2
        assert s["win_rate"] == 0.5
        assert s["total_pnl"] == pytest.approx(400.0)
        assert s["avg_win"] == pytest.approx(200.0)
        assert s["avg_loss"] == pytest.approx(-100.0)
        assert s["profit_factor"] == pytest.approx(3.0)  # 600 / 200
        assert s["best_trade"] == pytest.approx(300.0)
        assert s["worst_trade"] == pytest.approx(-150.0)

    def test_profit_factor_guarded_when_no_losses(self, db):
        _insert_trade(db, "w1", 100.0)
        _insert_trade(db, "w2", 50.0)

        s = db.get_stats_summary()
        assert s["winning_trades"] == 2
        assert s["losing_trades"] == 0
        assert s["win_rate"] == 1.0
        # No losing trades -> guard returns 0.0 (no ZeroDivisionError / inf).
        assert s["profit_factor"] == 0.0
        assert s["best_trade"] == pytest.approx(100.0)
        assert s["worst_trade"] == pytest.approx(50.0)  # MIN over the two wins
