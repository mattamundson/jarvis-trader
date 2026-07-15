"""
Tests for US-2141: WFE live tracking endpoints
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app
from routers import wfe_router
from routers.wfe_router import _compute_snapshot_stats, _get_week_start


@pytest.fixture
def db_connection():
    """Create an in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Create paper_trades table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT    NOT NULL UNIQUE,
            symbol          TEXT    NOT NULL,
            side            TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            entry_price     REAL    NOT NULL,
            exit_price      REAL,
            entry_time      TEXT    NOT NULL,
            exit_time       TEXT,
            pnl             REAL,
            status          TEXT    NOT NULL DEFAULT 'open'
        )
        """
    )

    # Create wfe_snapshots table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wfe_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL,
            week_start      TEXT    NOT NULL,
            trades          INTEGER NOT NULL DEFAULT 0,
            win_rate        REAL,
            profit_factor   REAL,
            sharpe          REAL,
            max_dd          REAL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def wfe_client_with_db(db_connection):
    """TestClient with WFE routes using the in-memory DB (CI has no migrated SQLite file)."""

    async def _override_conn():
        yield db_connection

    app.dependency_overrides[wfe_router.get_db_connection] = _override_conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(wfe_router.get_db_connection, None)


class TestGetWeekStart:
    """Test _get_week_start() helper function."""

    def test_monday_returns_same_date(self):
        """If date is Monday, return the same date."""
        # 2026-04-06 is a Monday
        date = datetime(2026, 4, 6)
        result = _get_week_start(date)
        assert result == "2026-04-06"

    def test_tuesday_returns_monday(self):
        """If date is Tuesday, return the previous Monday."""
        # 2026-04-07 is a Tuesday
        date = datetime(2026, 4, 7)
        result = _get_week_start(date)
        assert result == "2026-04-06"

    def test_sunday_returns_previous_monday(self):
        """If date is Sunday, return the previous Monday."""
        # 2026-04-12 is a Sunday
        date = datetime(2026, 4, 12)
        result = _get_week_start(date)
        assert result == "2026-04-06"

    def test_none_uses_current_date(self):
        """If date is None, use current UTC date."""
        result = _get_week_start(None)
        # Should be a valid date string
        assert len(result) == 10  # YYYY-MM-DD
        assert result.count("-") == 2


class TestComputeSnapshotStats:
    """Test _compute_snapshot_stats() function."""

    def test_empty_trades_returns_zeros(self, db_connection):
        """If no closed trades exist, return zeros."""
        week_start = "2026-04-06"
        stats = _compute_snapshot_stats("MCL", week_start, db_connection)

        assert stats["trades"] == 0
        assert stats["win_rate"] is None
        assert stats["profit_factor"] is None

    def test_single_winning_trade(self, db_connection):
        """With one winning trade, calculate metrics correctly."""
        week_start = "2026-04-06"
        week_end = "2026-04-12T23:59:59"

        # Insert a winning trade
        db_connection.execute(
            """
            INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, exit_price, entry_time, exit_time, pnl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trade1",
                "MCL",
                "buy",
                1.0,
                100.0,
                105.0,
                "2026-04-06T10:00:00",
                "2026-04-06T11:00:00",
                500.0,  # pnl
                "closed",
            ),
        )
        db_connection.commit()

        stats = _compute_snapshot_stats("MCL", week_start, db_connection)

        assert stats["trades"] == 1
        assert stats["win_rate"] == 1.0  # 1 win / 1 trade
        assert stats["profit_factor"] == 500.0  # winning_pnl / abs(losing_pnl)

    def test_multiple_trades_mixed(self, db_connection):
        """With mixed winning and losing trades, calculate correctly."""
        week_start = "2026-04-06"

        trades = [
            ("trade1", 500.0, "2026-04-06T10:00:00"),  # win
            ("trade2", -200.0, "2026-04-06T11:00:00"),  # loss
            ("trade3", 300.0, "2026-04-06T12:00:00"),  # win
        ]

        for trade_id, pnl, exit_time in trades:
            db_connection.execute(
                """
                INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, exit_price, entry_time, exit_time, pnl, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id,
                    "MCL",
                    "buy",
                    1.0,
                    100.0,
                    105.0,
                    exit_time,  # simplified: same time
                    exit_time,
                    pnl,
                    "closed",
                ),
            )
        db_connection.commit()

        stats = _compute_snapshot_stats("MCL", week_start, db_connection)

        assert stats["trades"] == 3
        assert stats["win_rate"] == pytest.approx(2.0 / 3.0, rel=1e-3)  # 2 wins / 3 trades
        # profit_factor = (500 + 300) / abs(-200) = 800 / 200 = 4.0
        assert stats["profit_factor"] == 4.0

    def test_sharpe_matches_canonical_metrics_formula(self, db_connection):
        """
        sharpe returned by the snapshot must equal backtest/metrics.py's canonical
        Sharpe (per-trade RETURNS as a fraction of initial_capital, annualized by
        sqrt(252)) -- not a raw-dollar, non-annualized mean/std. Regression test for
        the two-endpoints-disagree bug: the OLD implementation here computed
        statistics.mean(pnls) / statistics.stdev(pnls) with no capital-normalization
        and no annualization, which numerically differs from this by orders of
        magnitude.
        """
        from datetime import datetime as dt

        from backtest.metrics import compute_sharpe_sortino
        from backtest.trade_manager import BacktestResult, Trade

        week_start = "2026-04-06"
        pnls = [500.0, -200.0, 300.0, -150.0, 700.0]

        for i, pnl in enumerate(pnls):
            exit_time = f"2026-04-{6 + i:02d}T10:00:00"
            db_connection.execute(
                """
                INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, exit_price, entry_time, exit_time, pnl, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"trade{i}",
                    "MCL",
                    "buy",
                    1.0,
                    100.0,
                    105.0,
                    exit_time,
                    exit_time,
                    pnl,
                    "closed",
                ),
            )
        db_connection.commit()

        stats = _compute_snapshot_stats("MCL", week_start, db_connection)

        # Independently compute the expected value via the SAME canonical function
        # the router is supposed to call, from the same raw pnl list.
        expected_trades = [
            Trade(
                entry_date=dt.utcnow(),
                symbol="MCL",
                direction="long" if p >= 0 else "short",
                entry_price=0.0,
                stop_price=0.0,
                target_1=0.0,
                target_2=0.0,
                contracts=1,
                multiplier=1.0,
                pnl=p,
            )
            for p in pnls
        ]
        expected_result = BacktestResult(
            symbol="MCL",
            start_date=week_start,
            end_date="irrelevant",
            initial_capital=settings.INITIAL_CAPITAL,
            final_capital=settings.INITIAL_CAPITAL + sum(pnls),
            trades=expected_trades,
        )
        compute_sharpe_sortino(expected_result)

        assert stats["sharpe"] == pytest.approx(round(expected_result.sharpe_ratio, 4), rel=1e-6)

        # Sanity check this isn't accidentally still the OLD raw-dollar formula:
        # old_sharpe = mean(pnls)/stdev(pnls) with NO annualization, NO capital scaling.
        import statistics as _statistics

        old_sharpe = _statistics.mean(pnls) / _statistics.stdev(pnls)
        assert stats["sharpe"] != pytest.approx(old_sharpe, rel=1e-6)


class TestWFERouter:
    """Test WFE router endpoints."""

    def test_post_snapshot_creates_snapshot(self, wfe_client_with_db):
        """POST /wfe/snapshot should create a snapshot."""
        client = wfe_client_with_db
        response = client.post("/wfe/snapshot", headers={"X-API-Key": settings.API_KEY})

        # Should return 200 with status='ok'
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "snapshots_created" in data

    def test_get_snapshots_returns_list(self, wfe_client_with_db):
        """GET /wfe/snapshots should return list of snapshots."""
        client = wfe_client_with_db
        response = client.get("/wfe/snapshots", headers={"X-API-Key": settings.API_KEY})

        assert response.status_code == 200
        data = response.json()
        assert "snapshots" in data
        assert "total_count" in data
        assert isinstance(data["snapshots"], list)

    def test_get_snapshots_with_symbol_filter(self, wfe_client_with_db):
        """GET /wfe/snapshots?symbol=MCL should filter by symbol."""
        client = wfe_client_with_db
        response = client.get("/wfe/snapshots?symbol=MCL", headers={"X-API-Key": settings.API_KEY})

        assert response.status_code == 200
        data = response.json()
        for snapshot in data["snapshots"]:
            assert snapshot["symbol"] == "MCL"
