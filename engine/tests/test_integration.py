"""
JARVIS TRADER — Integration Test Suite
========================================
Covers Phase 1 (SQLite persistence) and Phase 2 (IB Gateway + Safety) components.

Run all tests:
    cd engine
    python -m pytest tests/test_integration.py -v

Run only offline tests (no engine required):
    python -m pytest tests/test_integration.py -v -k "not Portfolio"

Run only live endpoint tests (requires engine running on localhost:8010):
    python -m pytest tests/test_integration.py -v -k "Portfolio"
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load engine .env so API_KEY is available via os.environ.get("API_KEY")
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Path bootstrap — make the engine package importable from tests/
# ---------------------------------------------------------------------------
_ENGINE_DIR = Path(__file__).parent.parent  # engine/
_PROJECT_ROOT = _ENGINE_DIR.parent  # jarvis-trader/
if str(_ENGINE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR.parent))

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Helper — probe whether the engine is up before running endpoint tests
# ---------------------------------------------------------------------------
_ENGINE_BASE = "http://localhost:8010"


def _engine_running() -> bool:
    """
    True only for a full JARVIS stack on port 8010 (not a generic /health-only service).
    See ``live_engine_probe.jarvis_engine_ready``.
    """
    from live_engine_probe import jarvis_engine_ready

    return jarvis_engine_ready(_ENGINE_BASE)


def _engine_testable() -> bool:
    """True only if the engine is up AND accepts our API key (authed 200).

    ``_engine_running()`` / ``jarvis_engine_ready`` treat a 401 as "routed" (the
    JARVIS app is there), so they return True even when no valid key is in the
    env. The live endpoint smoke tests below assert HTTP 200, which a 401 fails —
    so when the engine is up but not authable (e.g. a dev ran the suite without
    sourcing ``engine/.env`` so ``API_KEY`` is unset), skip rather than emit
    misleading auth failures. CI has no engine, so this short-circuits at
    ``_engine_running()`` and the class skips as before.
    """
    if not _engine_running():
        return False
    req = urllib.request.Request(f"{_ENGINE_BASE}/safety/status")
    req.add_header("X-API-Key", os.environ.get("API_KEY") or "test-key")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _session4_api_ready() -> bool:
    """True when Session 4 HTTP contract routes are deployed (see live_engine_probe)."""
    from live_engine_probe import session4_api_ready

    return session4_api_ready(_ENGINE_BASE)


def _live_analytics_contract_ready() -> bool:
    """True when live :8010 serves current analytics performance schema."""
    from live_engine_probe import live_analytics_contract_ready

    return live_analytics_contract_ready(_ENGINE_BASE)


# ===========================================================================
# TestSQLitePersistence
# ===========================================================================


class TestSQLitePersistence(unittest.TestCase):
    """Verify every public DatabaseManager method against a real SQLite file."""

    def setUp(self) -> None:
        """Create a fresh temp directory and an initialised DatabaseManager."""
        self._tmpdir = tempfile.mkdtemp(prefix="jarvis_test_db_")
        db_path = os.path.join(self._tmpdir, "test.db")

        from engine.database.schema import DatabaseManager

        self.db = DatabaseManager(db_path=db_path)
        self.db.initialize()

    def tearDown(self) -> None:
        """Remove the temp directory including the SQLite file."""
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── table existence ────────────────────────────────────────────────────

    def test_db_initializes_cleanly(self) -> None:
        """All expected tables must exist after initialize()."""
        from engine.database.schema import DatabaseManager

        db_path = os.path.join(self._tmpdir, "clean_init.db")
        db = DatabaseManager(db_path=db_path)
        db.initialize()

        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        for required in ("paper_trades", "decisions", "daily_pnl", "positions", "settings"):
            self.assertIn(
                required,
                tables,
                msg=f"Expected table '{required}' not found after initialize(). "
                f"Tables present: {tables}",
            )

    # ── trade lifecycle ────────────────────────────────────────────────────

    def test_trade_lifecycle(self) -> None:
        """Insert a trade, verify it is open, then close it and verify closed."""
        trade_id = str(uuid.uuid4())

        row_pk = self.db.insert_trade(
            trade_id=trade_id,
            symbol="MES",
            side="buy",
            quantity=1.0,
            entry_price=5200.0,
        )
        self.assertIsInstance(row_pk, int, "insert_trade should return an int PK")
        self.assertGreater(row_pk, 0)

        open_trades = self.db.get_open_trades()
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["trade_id"], trade_id)
        self.assertEqual(open_trades[0]["status"], "open")

        closed = self.db.close_trade(
            trade_id=trade_id,
            exit_price=5220.0,
            pnl=100.0,
        )
        self.assertTrue(closed, "close_trade should return True when a row is updated")

        open_after = self.db.get_open_trades()
        self.assertEqual(len(open_after), 0, "No open trades should remain after close")

        closed_trades = self.db.get_closed_trades()
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["trade_id"], trade_id)
        self.assertEqual(closed_trades[0]["status"], "closed")
        self.assertAlmostEqual(closed_trades[0]["exit_price"], 5220.0)
        self.assertAlmostEqual(closed_trades[0]["pnl"], 100.0)

    def test_close_trade_returns_false_for_unknown_id(self) -> None:
        """close_trade must return False when the trade_id is not found."""
        result = self.db.close_trade(
            trade_id="nonexistent-id",
            exit_price=5000.0,
            pnl=0.0,
        )
        self.assertFalse(result)

    # ── persistence across restart ─────────────────────────────────────────

    def test_trade_persists_across_restart(self) -> None:
        """
        Write a trade to DB, create a brand-new DatabaseManager pointing at
        the same file, and confirm the trade can still be read back.
        """
        from engine.database.schema import DatabaseManager

        shared_db_path = os.path.join(self._tmpdir, "shared.db")

        # First manager — write
        db1 = DatabaseManager(db_path=shared_db_path)
        db1.initialize()
        trade_id = str(uuid.uuid4())
        db1.insert_trade(
            trade_id=trade_id,
            symbol="MNQ",
            side="sell",
            quantity=2.0,
            entry_price=19500.0,
        )

        # Second manager — simulates restart
        db2 = DatabaseManager(db_path=shared_db_path)
        db2.initialize()  # idempotent — must not wipe existing data
        recovered = db2.get_trade_by_id(trade_id)

        self.assertIsNotNone(recovered, "Trade should survive a manager restart")
        self.assertEqual(recovered["symbol"], "MNQ")
        self.assertAlmostEqual(recovered["quantity"], 2.0)
        self.assertEqual(recovered["status"], "open")

    # ── daily P&L ──────────────────────────────────────────────────────────

    def test_daily_pnl_snapshot(self) -> None:
        """upsert_daily_pnl then query it back — values must round-trip."""
        self.db.upsert_daily_pnl(
            date="2026-03-29",
            starting_balance=10000.0,
            ending_balance=10350.0,
            realized_pnl=350.0,
            unrealized_pnl=0.0,
            total_trades=4,
            winning_trades=3,
            losing_trades=1,
            max_drawdown=-120.0,
        )

        rows = self.db.get_daily_pnl(start_date="2026-03-29", end_date="2026-03-29")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-03-29")
        self.assertAlmostEqual(row["realized_pnl"], 350.0)
        self.assertEqual(row["total_trades"], 4)
        self.assertEqual(row["winning_trades"], 3)
        self.assertAlmostEqual(row["max_drawdown"], -120.0)

        # Upsert again (should replace, not duplicate)
        self.db.upsert_daily_pnl(
            date="2026-03-29",
            starting_balance=10000.0,
            ending_balance=10400.0,
            realized_pnl=400.0,
            unrealized_pnl=50.0,
            total_trades=5,
            winning_trades=4,
            losing_trades=1,
            max_drawdown=-80.0,
        )
        rows_after = self.db.get_daily_pnl(start_date="2026-03-29", end_date="2026-03-29")
        self.assertEqual(len(rows_after), 1, "Upsert should not create a duplicate row")
        self.assertAlmostEqual(rows_after[0]["realized_pnl"], 400.0)

    def test_daily_pnl_latest(self) -> None:
        """get_latest_daily_pnl returns the most recent row."""
        for date, pnl in [("2026-03-27", 100.0), ("2026-03-28", 200.0), ("2026-03-29", 50.0)]:
            self.db.upsert_daily_pnl(
                date=date,
                starting_balance=10000.0,
                ending_balance=10000.0 + pnl,
                realized_pnl=pnl,
                unrealized_pnl=0.0,
                total_trades=2,
                winning_trades=1,
                losing_trades=1,
                max_drawdown=-50.0,
            )

        latest = self.db.get_latest_daily_pnl()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["date"], "2026-03-29")

    # ── positions ──────────────────────────────────────────────────────────

    def test_position_upsert(self) -> None:
        """upsert_position, update it, then delete it — verify each step."""
        self.db.upsert_position(
            symbol="MES",
            quantity=2.0,
            entry_price=5200.0,
            current_price=5210.0,
            unrealized_pnl=100.0,
        )

        pos = self.db.get_position("MES")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos["quantity"], 2.0)
        self.assertAlmostEqual(pos["entry_price"], 5200.0)
        self.assertAlmostEqual(pos["unrealized_pnl"], 100.0)

        # Update price tick
        updated = self.db.update_position_price(
            symbol="MES",
            current_price=5230.0,
            unrealized_pnl=300.0,
        )
        self.assertTrue(updated)

        pos_after = self.db.get_position("MES")
        self.assertAlmostEqual(pos_after["current_price"], 5230.0)
        self.assertAlmostEqual(pos_after["unrealized_pnl"], 300.0)

        # Delete position
        deleted = self.db.delete_position("MES")
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_position("MES"))

    def test_position_update_returns_false_for_unknown(self) -> None:
        """update_position_price must return False for a symbol not in DB."""
        result = self.db.update_position_price(
            symbol="UNKNOWN",
            current_price=100.0,
            unrealized_pnl=0.0,
        )
        self.assertFalse(result)


# ===========================================================================
# TestPositionSizing
# ===========================================================================


class TestPositionSizing(unittest.TestCase):
    """Verify calculate_position_size arithmetic and edge-case handling."""

    def setUp(self) -> None:
        from engine.utils.position_sizing import calculate_position_size

        self._calc = calculate_position_size

    # ── standard case ──────────────────────────────────────────────────────

    def test_mes_standard(self) -> None:
        """
        MES, $10k account, ATR=12.5 → expect 2 contracts.

        Math:
            risk_per_trade          = $10,000 * 0.01 = $100
            stop_distance           = 12.5 * 0.70    = 8.75 pts
            dollar_risk_per_contract = 8.75 * $5     = $43.75
            raw_contracts           = floor(100 / 43.75) = 2
            clamped [1, 2]          = 2
        """
        result = self._calc(
            symbol="MES",
            account_value=10_000.0,
            atr=12.5,
            risk_pct=0.01,
            atr_stop_multiplier=0.70,
            max_contracts=2,
        )
        self.assertEqual(result.contracts, 2)
        self.assertEqual(result.symbol, "MES")
        self.assertAlmostEqual(result.risk_per_trade, 100.0)
        self.assertAlmostEqual(result.stop_distance, 8.75)
        self.assertAlmostEqual(result.dollar_risk_per_contract, 43.75)

    # ── zero ATR fallback ──────────────────────────────────────────────────

    def test_fallback_on_zero_atr(self) -> None:
        """ATR=0 should produce exactly 1 contract (safe fallback)."""
        result = self._calc(
            symbol="MES",
            account_value=50_000.0,
            atr=0.0,
        )
        self.assertEqual(result.contracts, 1, "Zero ATR must always fall back to 1 contract")
        self.assertAlmostEqual(result.stop_distance, 0.0)

    def test_fallback_on_none_atr(self) -> None:
        """ATR=None should also produce exactly 1 contract."""
        result = self._calc(
            symbol="MNQ",
            account_value=25_000.0,
            atr=None,
        )
        self.assertEqual(result.contracts, 1)

    # ── max_contracts cap ──────────────────────────────────────────────────

    def test_max_contracts_cap(self) -> None:
        """
        With a very large account and tiny ATR the math would give many contracts;
        the result must be clamped to max_contracts.
        """
        result = self._calc(
            symbol="MES",
            account_value=1_000_000.0,
            atr=1.0,  # tiny stop → lots of raw contracts
            risk_pct=0.01,
            max_contracts=3,
        )
        self.assertLessEqual(
            result.contracts,
            3,
            "Contracts must never exceed max_contracts cap",
        )

    # ── unknown symbol ─────────────────────────────────────────────────────

    def test_unknown_symbol_is_refused_not_guessed(self) -> None:
        """An unrecognised symbol must RAISE, not get a silently-invented multiplier.

        This test previously asserted the opposite -- that an unknown symbol
        falls back to $5/pt "same as MES". That fallback was the bug: $5/pt is a
        FUTURES multiplier, so every equity (SPY/QQQ/AAPL/TSLA, all on the
        OPTIONS_WATCHLIST) was sized as a micro future. TSLA at ~$390 with a $151
        risk budget and a ~$2 stop should be ~75 shares; the engine computed 15
        and clamped to 2.

        Worse, portfolio.tracker RAISED on those same symbols, so the engine
        could size a position its own P&L layer refused to price. Sizing and P&L
        must resolve a symbol identically or not at all -- refusing to size is
        strictly safer than opening an unpriceable position.
        """
        from engine.utils.position_sizing import (
            INSTRUMENT_MULTIPLIERS,
            UnknownInstrumentMultiplierError,
        )

        unknown = "UNKNOWN_XYZ"
        self.assertNotIn(unknown, INSTRUMENT_MULTIPLIERS)

        with self.assertRaises(UnknownInstrumentMultiplierError):
            self._calc(
                symbol=unknown,
                account_value=10_000.0,
                atr=12.5,
                risk_pct=0.01,
                atr_stop_multiplier=0.70,
                max_contracts=5,
            )

    def test_unknown_symbol_env_escape_falls_back_to_1x(self) -> None:
        """ALLOW_DEFAULT_MULTIPLIER=1 restores a fallback -- at 1.0, not 5.0.

        Mirrors portfolio.tracker's escape hatch exactly, so the two layers stay
        interchangeable. 1.0 is the honest default: it under-states a futures
        P&L loudly rather than over-stating an equity position silently.
        """
        import os
        from unittest import mock

        from engine.utils.position_sizing import _DEFAULT_MULTIPLIER

        self.assertEqual(_DEFAULT_MULTIPLIER, 1.0)
        with mock.patch.dict(os.environ, {"ALLOW_DEFAULT_MULTIPLIER": "1"}):
            result = self._calc(
                symbol="UNKNOWN_XYZ",
                account_value=10_000.0,
                atr=12.5,
                risk_pct=0.01,
                atr_stop_multiplier=0.70,
                max_contracts=5,
            )
        self.assertGreaterEqual(result.contracts, 1)
        self.assertAlmostEqual(
            result.dollar_risk_per_contract, result.stop_distance * 1.0, places=4
        )

    # ── account too small ──────────────────────────────────────────────────

    def test_small_account_fallback(self) -> None:
        """Account < $1,000 must produce 1 contract regardless of ATR."""
        result = self._calc(
            symbol="MES",
            account_value=500.0,
            atr=10.0,
        )
        self.assertEqual(result.contracts, 1)


# ===========================================================================
# TestTrackerSQLiteIntegration
# ===========================================================================


class TestTrackerSQLiteIntegration(unittest.TestCase):
    """Verify PortfolioTracker <-> DatabaseManager integration."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="jarvis_test_tracker_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_db(self, name: str = "test.db"):
        """Create and initialise a fresh DatabaseManager in the temp dir."""
        from engine.database.schema import DatabaseManager

        db_path = os.path.join(self._tmpdir, name)
        db = DatabaseManager(db_path=db_path)
        db.initialize()
        return db

    def _make_tracker(self, db=None, jsonl_name: str = "trades.jsonl"):
        """Create a PortfolioTracker wired to a temp JSONL file."""
        from engine.portfolio.tracker import PortfolioTracker

        jsonl_path = Path(self._tmpdir) / jsonl_name
        return PortfolioTracker(store_path=jsonl_path, db_manager=db)

    # ── with DB ────────────────────────────────────────────────────────────

    def test_tracker_uses_db_when_provided(self) -> None:
        """
        When db_manager is provided, open_trade should persist a record.

        The tracker calls db.insert_paper_trade() which is a Phase-3 bridge
        method not yet present on DatabaseManager — the tracker silently falls
        back to in-memory state on AttributeError.  This test therefore verifies:
          1. The tracker still returns a valid trade_id (in-memory path works).
          2. In-memory open positions are populated correctly.

        Once Phase-3 adds insert_paper_trade() to DatabaseManager, the DB
        assertion at the bottom of this test should be uncommented.
        """
        db = self._make_db()
        tracker = self._make_tracker(db=db)

        trade_id = tracker.open_trade(
            symbol="MES",
            action="buy",
            quantity=1,
            price=5200.0,
            notes="integration test",
        )
        self.assertIsInstance(trade_id, str)

        # Verify in-memory state is always populated regardless of DB bridge
        open_pos = tracker.get_open_positions()
        self.assertEqual(len(open_pos), 1)
        self.assertEqual(open_pos[0]["symbol"], "MES")

        # Phase 3: Uncomment once DatabaseManager gains
        # insert_paper_trade() — at that point the tracker will write to DB
        # and this assertion should hold:
        #
        #   db_open = db.get_open_trades(symbol="MES")
        #   self.assertEqual(len(db_open), 1, "Trade should appear in DB via insert_paper_trade")

    def test_tracker_close_persists_to_db(self) -> None:
        """
        close_trade should update in-memory state (and DB when bridge exists).

        The tracker calls db.close_paper_trade() which is a Phase-3 bridge
        method not yet present on DatabaseManager.  The test verifies that the
        in-memory close still works correctly and the JSONL audit log is written.

        Once Phase-3 adds close_paper_trade(), the DB assertion should be
        uncommented to enforce full persistence.
        """
        db = self._make_db()
        tracker = self._make_tracker(db=db)

        trade_id = tracker.open_trade("MES", "buy", 1, 5200.0)
        closed_trade = tracker.close_trade(trade_id, exit_price=5250.0)

        # In-memory close must always work
        self.assertFalse(closed_trade.is_open)
        self.assertAlmostEqual(closed_trade.exit_price, 5250.0)
        # (5250-5200)*1*5.0 (MES multiplier) = 250.0 gross, minus $1.50/contract
        # commission (Phase 2 financial-calc fix) = 248.50 net.
        self.assertAlmostEqual(closed_trade.pnl, 248.50)

        # No open trades remaining in memory
        self.assertEqual(len(tracker.get_open_positions()), 0)

        # Phase 3: Uncomment once DatabaseManager gains
        # close_paper_trade() — at that point the DB record should be updated:
        #
        #   closed = db.get_closed_trades(symbol="MES")
        #   self.assertEqual(len(closed), 1)
        #   self.assertAlmostEqual(closed[0]["exit_price"], 5250.0)

    # ── without DB (in-memory only) ────────────────────────────────────────

    def test_tracker_fallback_without_db(self) -> None:
        """
        When no db_manager is provided the tracker must still work correctly
        using only in-memory state + JSONL audit log.
        """
        tracker = self._make_tracker(db=None)

        trade_id = tracker.open_trade("MNQ", "buy", 2, 19500.0)
        self.assertIsInstance(trade_id, str)

        positions = tracker.get_open_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "MNQ")

        closed_trade = tracker.close_trade(trade_id, exit_price=19600.0)
        self.assertIsNotNone(closed_trade)
        self.assertFalse(closed_trade.is_open)
        # (19600-19500)*2*2.0 (MNQ multiplier) = 400.0 gross, minus $1.50/contract
        # commission * 2 contracts = 3.00 → 397.00 net.
        self.assertAlmostEqual(closed_trade.pnl, 397.00)

        positions_after = tracker.get_open_positions()
        self.assertEqual(len(positions_after), 0)

    def test_tracker_close_raises_on_unknown_id(self) -> None:
        """close_trade must raise KeyError when the trade_id is not found."""
        tracker = self._make_tracker(db=None)
        with self.assertRaises(KeyError):
            tracker.close_trade("nonexistent-trade-id", exit_price=5000.0)

    def test_tracker_pnl_long(self) -> None:
        """P&L for a long trade: (exit - entry) * qty."""
        tracker = self._make_tracker(db=None)
        trade_id = tracker.open_trade("MES", "buy", 3, 5000.0)
        closed = tracker.close_trade(trade_id, exit_price=5010.0)
        # (5010-5000)*3*5.0 (MES multiplier) = 150.0 gross, minus $1.50/contract
        # commission * 3 contracts = 4.50 → 145.50 net.
        self.assertAlmostEqual(closed.pnl, 145.50)

    def test_tracker_pnl_short(self) -> None:
        """P&L for a short trade: (entry - exit) * qty."""
        tracker = self._make_tracker(db=None)
        trade_id = tracker.open_trade("MES", "sell", 2, 5100.0)
        closed = tracker.close_trade(trade_id, exit_price=5080.0)
        # (5100-5080)*2*5.0 (MES multiplier) = 200.0 gross, minus $1.50/contract
        # commission * 2 contracts = 3.00 → 197.00 net.
        self.assertAlmostEqual(closed.pnl, 197.00)


# ===========================================================================
# TestPortfolioEndpoints  (requires engine running on localhost:8010)
# ===========================================================================


@unittest.skipIf(
    not _engine_testable(),
    "Engine not running or not authable on localhost:8010 (set API_KEY to run live endpoint "
    "tests) — skipping",
)
class TestPortfolioEndpoints(unittest.TestCase):
    """
    Live HTTP smoke-tests against a running JARVIS engine.

    These tests are skipped automatically when the engine is not up.
    Start the engine with:  cd engine && uvicorn main:app --port 8010

    Route availability notes
    ------------------------
    Phase 1/2 routes (currently live):
        /health                    — core health check
        /portfolio                 — portfolio summary
        /safety/status             — safety layer status
        /decisions/recent          — recent pipeline decisions

    Phase 3 routes (not yet wired — tests document expected future paths):
        /portfolio/history/trades  — trade history
        /portfolio/history/daily-pnl
        /safety/circuit-breakers
        /analytics/performance
    """

    BASE = _ENGINE_BASE

    def _get(self, path: str) -> tuple[int, dict]:
        """GET the given path and return (status_code, parsed_json).

        10s timeout — post-P1.9 fix, /portfolio/summary must return within
        this envelope (tick-only path via IBKR/Schwab, no TV chart-lock).
        """
        url = f"{self.BASE}{path}"
        req = urllib.request.Request(url)
        req.add_header("X-API-Key", os.environ.get("API_KEY") or "test-key")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body

    # ── Live Phase 1/2 routes ──────────────────────────────────────────────

    def test_health_endpoint(self) -> None:
        """GET /health must return HTTP 200 with a 'status' field."""
        status, body = self._get("/health")
        self.assertEqual(status, 200, f"Expected HTTP 200 from /health, got {status}")
        self.assertIn("status", body, f"/health missing 'status' field. Body: {body}")

    def test_portfolio_endpoint(self) -> None:
        """GET /portfolio must return HTTP 200."""
        status, body = self._get("/portfolio")
        self.assertEqual(
            status,
            200,
            f"Expected HTTP 200 from /portfolio, got {status}",
        )

    def test_safety_status_endpoint(self) -> None:
        """GET /safety/status must return 200."""
        status, body = self._get("/safety/status")
        self.assertEqual(
            status,
            200,
            f"Expected HTTP 200 from /safety/status, got {status}",
        )

    def test_decisions_recent_endpoint(self) -> None:
        """GET /decisions/recent must return 200."""
        status, body = self._get("/decisions/recent")
        self.assertEqual(
            status,
            200,
            f"Expected HTTP 200 from /decisions/recent, got {status}",
        )

    # ── Phase 3 route stubs — document expected paths (404 acceptable now) ──

    def test_history_trades_endpoint(self) -> None:
        """
        GET /portfolio/history/trades — Phase 3 route.
        Expected to return 200 once wired; currently may 404.
        Test documents the expected contract for Phase 3 completion.
        """
        status, body = self._get("/portfolio/history/trades")
        # Accept 200 (route live) or 404 (not yet wired in Phase 3)
        self.assertIn(
            status,
            (200, 404),
            f"Unexpected status {status} from /portfolio/history/trades",
        )
        if status == 200:
            # Enforce contract once route goes live
            self.assertIsInstance(body, (list, dict))

    def test_daily_pnl_endpoint(self) -> None:
        """
        GET /portfolio/history/daily-pnl — Phase 3 route.
        Expected to return 200 once wired; currently may 404.
        """
        status, body = self._get("/portfolio/history/daily-pnl")
        self.assertIn(
            status,
            (200, 404),
            f"Unexpected status {status} from /portfolio/history/daily-pnl",
        )
        if status == 200:
            self.assertIsInstance(body, (list, dict))

    def test_circuit_breakers_endpoint(self) -> None:
        """
        GET /safety/circuit-breakers — Phase 3 route.
        When live, must return 200 with an all_clear field.
        """
        status, body = self._get("/safety/circuit-breakers")
        self.assertIn(
            status,
            (200, 404),
            f"Unexpected status {status} from /safety/circuit-breakers",
        )
        if status == 200:
            self.assertIn(
                "all_clear",
                body,
                f"/safety/circuit-breakers missing 'all_clear' field. Body: {body}",
            )

    @unittest.skipUnless(
        _live_analytics_contract_ready(),
        "Live engine analytics contract mismatch — restart engine after deploy",
    )
    def test_performance_endpoint(self) -> None:
        """
        GET /analytics/performance — Phase 3 route.
        When live, must return 200 with a status field.
        """
        status, body = self._get("/analytics/performance")
        self.assertIn(
            status,
            (200, 404),
            f"Unexpected status {status} from /analytics/performance",
        )
        if status == 200:
            self.assertIn(
                "status",
                body,
                f"/analytics/performance missing 'status' field. Body: {body}",
            )


# ===========================================================================
# === Webhook Router Tests ===
# ===========================================================================

import json

# ---------------------------------------------------------------------------
# Build a minimal FastAPI TestClient that includes only the webhook router.
# We avoid importing engine.main (which pulls in heavy lifespan dependencies)
# and instead compose a lightweight app from the router directly.
# ---------------------------------------------------------------------------

try:
    from engine.routers.webhook_router import router as _webhook_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    _webhook_app = FastAPI()
    _webhook_app.include_router(_webhook_router)
    _webhook_client = TestClient(_webhook_app, raise_server_exceptions=False)
    _WEBHOOK_AVAILABLE = True
except Exception as _webhook_import_err:  # noqa: BLE001
    _WEBHOOK_AVAILABLE = False
    _webhook_import_err_msg = str(_webhook_import_err)


@unittest.skipUnless(_WEBHOOK_AVAILABLE, "Webhook router could not be imported")
class TestWebhookRouter(unittest.TestCase):
    """Integration tests for the TradingView webhook router."""

    @classmethod
    def setUpClass(cls) -> None:
        """Save webhook secret then unset it so most auth tests are deterministic."""
        # Preserve the secret so test_webhook_secret_validation can use it
        cls._original_secret = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "")
        os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
        # Re-import the module so the module-level WEBHOOK_SECRET re-reads the env.
        import engine.routers.webhook_router as _wh_mod

        _wh_mod.WEBHOOK_SECRET = ""

    # ── 1. GET /webhook/tradingview/test ────────────────────────────────────

    def test_webhook_get_test_endpoint(self) -> None:
        """GET /webhook/tradingview/test must return 200 with status 'ok'."""
        resp = _webhook_client.get("/webhook/tradingview/test")
        self.assertEqual(
            resp.status_code, 200, f"Expected 200, got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        self.assertIn("status", body, f"Response missing 'status' key. Body: {body}")
        self.assertEqual(body["status"], "ok", f"Expected status='ok', got {body['status']!r}")

    # ── 2. POST HOLD — ignored / received ───────────────────────────────────

    def test_webhook_post_hold_ignored(self) -> None:
        """
        POST /webhook/tradingview with action=HOLD.

        The router accepts HOLD (it is in valid_actions) but does NOT trigger
        the pipeline.  The response status is 'received' with pipeline_triggered=False.
        Accepting both 'received' and 'ignored' makes the test forward-compatible
        if the router is later updated to return 'ignored' explicitly.
        """
        payload = {"action": "HOLD", "symbol": "MES"}
        resp = _webhook_client.post("/webhook/tradingview", json=payload)
        self.assertEqual(
            resp.status_code, 200, f"Expected 200, got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        self.assertIn("status", body, f"Response missing 'status' key. Body: {body}")
        self.assertIn(
            body["status"],
            ("received", "ignored"),
            f"Expected status 'received' or 'ignored', got {body['status']!r}",
        )
        # If the router returns 'received', the pipeline must NOT have been triggered
        if body["status"] == "received":
            self.assertFalse(
                body.get("pipeline_triggered", False),
                "pipeline_triggered must be False for HOLD action",
            )

    # ── 3. POST LONG signal ─────────────────────────────────────────────────

    def test_webhook_post_long_signal(self) -> None:
        """
        POST /webhook/tradingview with a valid LONG payload.

        The pipeline callback may or may not be registered in the test app, so
        the response status is accepted as any of 'received', 'queued',
        'completed', or 'error'.
        """
        payload = {
            "symbol": "MES",
            "action": "LONG",
            "price": 5000.0,
            "timeframe": "1h",
            "indicator": "STC",
            "os_value": 12.5,
            "atr": 12.5,
            "regime": "BULL",
        }
        resp = _webhook_client.post("/webhook/tradingview", json=payload)
        self.assertEqual(
            resp.status_code, 200, f"Expected 200, got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        self.assertIn("status", body, f"Response missing 'status' key. Body: {body}")
        accepted_statuses = ("received", "queued", "completed", "error")
        self.assertIn(
            body["status"],
            accepted_statuses,
            f"Expected one of {accepted_statuses}, got {body['status']!r}",
        )

    # ── 4. POST malformed / invalid JSON ────────────────────────────────────

    def test_webhook_post_invalid_json(self) -> None:
        """
        POST /webhook/tradingview with malformed body must NOT return HTTP 500.
        FastAPI's request validation returns 422 for unparseable payloads.
        """
        resp = _webhook_client.post(
            "/webhook/tradingview",
            content=b"this is not json at all {{{",
            headers={"Content-Type": "application/json"},
        )
        self.assertNotEqual(
            resp.status_code,
            500,
            f"Server returned 500 on malformed input. Body: {resp.text}",
        )
        # Acceptable: 400 (explicit bad-request), 422 (FastAPI validation), or
        # 200 with an error status field
        self.assertIn(
            resp.status_code,
            (200, 400, 422),
            f"Unexpected status code {resp.status_code} for malformed JSON",
        )

    # ── 5. Webhook secret validation ────────────────────────────────────────

    def test_webhook_secret_validation(self) -> None:
        """
        If TRADINGVIEW_WEBHOOK_SECRET is configured the router must reject
        requests that omit or provide the wrong secret with 401 or 403.

        When no secret is configured this test is skipped.
        """
        import engine.routers.webhook_router as _wh_mod

        if not self._original_secret:
            raise unittest.SkipTest(
                "TRADINGVIEW_WEBHOOK_SECRET is not set — secret validation is disabled"
            )

        # Temporarily restore the secret so the router enforces validation
        _wh_mod.WEBHOOK_SECRET = self._original_secret
        try:
            # Wrong secret in body
            payload_wrong = {"symbol": "MES", "action": "LONG", "secret": "WRONG_SECRET"}
            resp_wrong = _webhook_client.post("/webhook/tradingview", json=payload_wrong)
            self.assertIn(
                resp_wrong.status_code,
                (401, 403),
                f"Expected 401/403 for wrong secret, got {resp_wrong.status_code}",
            )

            # Missing secret in body
            payload_missing = {"symbol": "MES", "action": "LONG"}
            resp_missing = _webhook_client.post("/webhook/tradingview", json=payload_missing)
            self.assertIn(
                resp_missing.status_code,
                (401, 403),
                f"Expected 401/403 for missing secret, got {resp_missing.status_code}",
            )
        finally:
            # Restore to no-secret state so subsequent tests remain deterministic
            _wh_mod.WEBHOOK_SECRET = ""


# ===========================================================================
# === Signal Pipeline E2E Tests ===
# ===========================================================================

# ---------------------------------------------------------------------------
# Build a minimal FastAPI TestClient that replicates the /pipeline/* routes
# from main.py but uses an in-memory SQLite DB and no live pipeline.
# This mirrors the same pattern used by TestWebhookRouter above.
# ---------------------------------------------------------------------------

try:
    import importlib.util as _importlib_util
    import tempfile as _tmpfile_mod
    import types as _types_mod

    from fastapi import FastAPI as _FastAPI
    from fastapi import HTTPException as _HTTPException
    from fastapi.testclient import TestClient as _TestClient
    from pydantic import BaseModel as _BaseModel

    # Load DatabaseManager directly from the schema module file to avoid
    # triggering engine.database.__init__.py which imports asyncpg (PostgreSQL).
    # We register a fake 'database' package in sys.modules with only the
    # modules we need (migrations + schema), so relative imports inside
    # schema.py resolve correctly without loading connection.py (asyncpg).
    if "database" not in sys.modules:
        _fake_db_pkg = _types_mod.ModuleType("database")
        _fake_db_pkg.__path__ = [str(_ENGINE_DIR / "database")]  # type: ignore[attr-defined]
        _fake_db_pkg.__package__ = "database"
        sys.modules["database"] = _fake_db_pkg

    _migrations_spec = _importlib_util.spec_from_file_location(
        "database.migrations",
        str(_ENGINE_DIR / "database" / "migrations.py"),
    )
    _migrations_mod = _importlib_util.module_from_spec(_migrations_spec)
    _migrations_mod.__package__ = "database"
    sys.modules.setdefault("database.migrations", _migrations_mod)
    _migrations_spec.loader.exec_module(_migrations_mod)  # type: ignore[union-attr]

    _schema_spec = _importlib_util.spec_from_file_location(
        "database.schema",
        str(_ENGINE_DIR / "database" / "schema.py"),
    )
    _schema_mod = _importlib_util.module_from_spec(_schema_spec)
    _schema_mod.__package__ = "database"
    sys.modules.setdefault("database.schema", _schema_mod)
    _schema_spec.loader.exec_module(_schema_mod)  # type: ignore[union-attr]
    _DatabaseManager = _schema_mod.DatabaseManager

    class _RunSignalRequest(_BaseModel):
        symbol: str
        action: str

    def _build_pipeline_app():
        """
        Build a lightweight FastAPI app that mirrors the /pipeline/* routes
        from main.py, backed by a real (but temp-dir) SQLite database and
        with trading_pipeline always set to None (no ANTHROPIC_API_KEY in tests).
        """
        _tmpdir = _tmpfile_mod.mkdtemp(prefix="jarvis_pipeline_test_")
        _db_path = _tmpdir + "/pipeline_test.db"
        _db = _DatabaseManager(db_path=_db_path)
        _db.initialize()

        _pipeline_instance = None  # Simulates no initialized pipeline

        _app = _FastAPI()

        @_app.get("/pipeline/history")
        async def _get_pipeline_history(limit: int = 50, symbol: str = ""):
            try:
                _limit = min(max(1, limit), 200)
                _runs = _db.get_pipeline_history(
                    limit=_limit,
                    symbol=symbol.upper() if symbol else None,
                )
                return {"runs": _runs, "count": len(_runs)}
            except Exception as exc:
                return {"runs": [], "count": 0, "error": str(exc)}

        @_app.post("/pipeline/run-signal")
        async def _pipeline_run_signal(req: _RunSignalRequest):
            valid_actions = {"LONG", "SHORT", "CLOSE", "HOLD"}
            action = req.action.upper()
            if action not in valid_actions:
                raise _HTTPException(
                    status_code=400,
                    detail=f"Invalid action: {req.action!r}. Must be one of {sorted(valid_actions)}",
                )
            if action == "HOLD":
                raise _HTTPException(
                    status_code=400,
                    detail="HOLD is not an actionable signal — pipeline will not run",
                )
            if _pipeline_instance is None:
                raise _HTTPException(
                    status_code=503,
                    detail="Trading pipeline not initialized. ANTHROPIC_API_KEY may be missing.",
                )
            # Unreachable in tests (pipeline is always None), but mirrors main.py contract
            raise _HTTPException(status_code=500, detail="Unexpected state")

        return _app, _db, _tmpdir

    _pipeline_app, _pipeline_db, _pipeline_tmpdir = _build_pipeline_app()
    _pipeline_client = _TestClient(_pipeline_app, raise_server_exceptions=False)
    _PIPELINE_AVAILABLE = True

except Exception as _pipeline_import_err:
    _PIPELINE_AVAILABLE = False
    _pipeline_import_err_msg = str(_pipeline_import_err)


@unittest.skipUnless(_PIPELINE_AVAILABLE, "Pipeline test app could not be built")
class TestSignalPipeline(unittest.TestCase):
    """
    End-to-end signal flow integration tests.

    Verifies the full chain: webhook action -> pipeline validation ->
    SQLite persistence, using an in-process TestClient backed by a real
    (but temporary) SQLite database.

    These tests do NOT require a running engine — they use the TestClient
    (httpx in-process). The trading pipeline itself is not initialized
    (no ANTHROPIC_API_KEY), so /pipeline/run-signal will return HTTP 503
    for valid LONG/SHORT/CLOSE actions.
    """

    # ── 1. GET /pipeline/history returns empty on fresh DB ──────────────────

    def test_pipeline_history_empty(self) -> None:
        """
        GET /pipeline/history must return {"runs": [], "count": 0} when
        no runs have been recorded in the in-memory test database.
        """
        resp = _pipeline_client.get("/pipeline/history")
        self.assertEqual(
            resp.status_code,
            200,
            f"Expected HTTP 200 from /pipeline/history, got {resp.status_code}. Body: {resp.text}",
        )
        body = resp.json()
        self.assertIn("runs", body, f"/pipeline/history missing 'runs' key. Body: {body}")
        self.assertIn("count", body, f"/pipeline/history missing 'count' key. Body: {body}")
        self.assertEqual(body["runs"], [], f"Expected empty runs list, got {body['runs']}")
        self.assertEqual(body["count"], 0, f"Expected count=0, got {body['count']}")

    # ── 2. POST /pipeline/run-signal with HOLD returns HTTP 400 ─────────────

    def test_pipeline_run_signal_invalid_action(self) -> None:
        """
        POST /pipeline/run-signal with action=HOLD must return HTTP 400.
        HOLD is explicitly rejected as a non-actionable signal.
        """
        payload = {"symbol": "MES", "action": "HOLD"}
        resp = _pipeline_client.post("/pipeline/run-signal", json=payload)
        self.assertEqual(
            resp.status_code,
            400,
            f"Expected HTTP 400 for HOLD action, got {resp.status_code}. Body: {resp.text}",
        )

    # ── 3. POST /pipeline/run-signal valid LONG → 503 (no pipeline) ─────────

    def test_pipeline_run_signal_no_pipeline(self) -> None:
        """
        POST /pipeline/run-signal with a valid LONG signal must return HTTP 503
        when the trading pipeline is not initialized (no ANTHROPIC_API_KEY in tests).

        Also accepts a 200 with status="error" in case the endpoint returns a
        graceful error dict rather than raising an HTTP exception.
        """
        payload = {"symbol": "MES", "action": "LONG"}
        resp = _pipeline_client.post("/pipeline/run-signal", json=payload)
        # Accept either HTTP 503 (explicit service unavailable) or 200 with error status
        if resp.status_code == 200:
            body = resp.json()
            self.assertIn(
                "status",
                body,
                f"Expected 'status' key in 200 response body. Body: {body}",
            )
            self.assertEqual(
                body["status"],
                "error",
                f"Expected status='error' in 200 body, got {body['status']!r}. Body: {body}",
            )
        else:
            self.assertEqual(
                resp.status_code,
                503,
                f"Expected HTTP 503 when pipeline not initialized, "
                f"got {resp.status_code}. Body: {resp.text}",
            )

    # ── 4. GET /pipeline/history response has required schema keys ───────────

    def test_pipeline_history_schema(self) -> None:
        """
        GET /pipeline/history response must contain 'runs' (list) and
        'count' (int) at the top level.
        """
        resp = _pipeline_client.get("/pipeline/history")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("runs", body, f"Missing 'runs' key. Body: {body}")
        self.assertIn("count", body, f"Missing 'count' key. Body: {body}")
        self.assertIsInstance(
            body["runs"], list, f"'runs' must be a list, got {type(body['runs']).__name__}"
        )
        self.assertIsInstance(
            body["count"], int, f"'count' must be an int, got {type(body['count']).__name__}"
        )

    # ── 5. GET /pipeline/history?limit=5 honours the limit param ────────────

    def test_pipeline_history_limit_param(self) -> None:
        """
        GET /pipeline/history?limit=5 must return at most 5 results.
        The limit query parameter must be honoured by the endpoint.
        """
        resp = _pipeline_client.get("/pipeline/history?limit=5")
        self.assertEqual(
            resp.status_code, 200, f"Expected 200, got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        self.assertIn("runs", body)
        self.assertLessEqual(
            len(body["runs"]),
            5,
            f"Expected at most 5 runs with limit=5, got {len(body['runs'])}",
        )

    # ── 6. GET /pipeline/history?symbol=MES filters by symbol ───────────────

    def test_pipeline_history_symbol_filter(self) -> None:
        """
        GET /pipeline/history?symbol=MES must only return runs with symbol=="MES".
        If the database is empty this test still passes (empty list is valid).
        """
        resp = _pipeline_client.get("/pipeline/history?symbol=MES")
        self.assertEqual(
            resp.status_code, 200, f"Expected 200, got {resp.status_code}. Body: {resp.text}"
        )
        body = resp.json()
        self.assertIn("runs", body)
        for run in body["runs"]:
            self.assertEqual(
                run.get("symbol"),
                "MES",
                f"Expected all runs to have symbol='MES', got {run.get('symbol')!r}. Run: {run}",
            )


# ===========================================================================
# === Webhook Deduplication Tests ===
# ===========================================================================


@unittest.skipUnless(_WEBHOOK_AVAILABLE, "Webhook router could not be imported")
class TestWebhookDedup(unittest.TestCase):
    """
    Verify that the deduplication logic in the webhook router correctly
    accepts the first signal and rejects an identical signal sent within
    the 30-second dedup window.
    """

    def setUp(self) -> None:
        """
        Reset the module-level dedup cache before each test so tests are
        fully independent of each other and of TestWebhookRouter runs.
        """
        import engine.routers.webhook_router as _wh_mod

        _wh_mod._dedup_cache.clear()
        # Ensure no webhook secret is set so auth does not interfere.
        os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
        _wh_mod.WEBHOOK_SECRET = ""

    # ── 1. First signal is accepted ────────────────────────────────────────

    def test_first_signal_accepted(self) -> None:
        """
        The first LONG signal for a given symbol/price must NOT be rejected
        as a duplicate.  Accepted statuses are any value except 'duplicate'.
        """
        payload = {
            "symbol": "MES",
            "action": "LONG",
            "price": 5100.0,
            "timeframe": "1h",
        }
        resp = _webhook_client.post("/webhook/tradingview", json=payload)
        self.assertEqual(
            resp.status_code,
            200,
            f"Expected HTTP 200, got {resp.status_code}. Body: {resp.text}",
        )
        body = resp.json()
        self.assertIn("status", body, f"Missing 'status' key. Body: {body}")
        self.assertNotEqual(
            body["status"],
            "duplicate",
            f"First signal should NOT be rejected as duplicate. Body: {body}",
        )

    # ── 2. Identical duplicate is rejected ─────────────────────────────────

    def test_duplicate_rejected(self) -> None:
        """
        Sending the exact same LONG signal twice in rapid succession must
        cause the second request to return status='duplicate'.
        """
        payload = {
            "symbol": "MES",
            "action": "LONG",
            "price": 5100.0,
            "timeframe": "1h",
        }
        # First call — must succeed (not duplicate)
        resp1 = _webhook_client.post("/webhook/tradingview", json=payload)
        self.assertEqual(resp1.status_code, 200, f"First request failed. Body: {resp1.text}")
        body1 = resp1.json()
        self.assertNotEqual(
            body1.get("status"),
            "duplicate",
            f"First call should not be a duplicate. Body: {body1}",
        )

        # Second call — must be rejected as duplicate
        resp2 = _webhook_client.post("/webhook/tradingview", json=payload)
        self.assertEqual(
            resp2.status_code, 200, f"Second request returned non-200. Body: {resp2.text}"
        )
        body2 = resp2.json()
        self.assertEqual(
            body2.get("status"),
            "duplicate",
            f"Second identical call should be rejected as duplicate. Body: {body2}",
        )
        self.assertIn(
            "message",
            body2,
            f"Duplicate response should include 'message' field. Body: {body2}",
        )


# ===========================================================================
# TestSession4Endpoints
# ===========================================================================


@unittest.skipUnless(
    _session4_api_ready(),
    "Session 4 API not deployed on localhost:8010 (or engine down) — skipping contract tests",
)
class TestSession4Endpoints(unittest.TestCase):
    """
    Smoke-tests for Session 4 endpoints.

    All tests are skipped automatically when the engine is not running.
    Start the engine with:  cd engine && uvicorn main:app --port 8010
    """

    BASE = _ENGINE_BASE

    def _get(self, path: str, params: dict | None = None) -> tuple[int, dict]:
        """GET the given path (with optional query params) and return (status_code, body)."""
        from urllib.parse import urlencode

        url = f"{self.BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("X-API-Key", os.environ.get("API_KEY") or "test-key")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise unittest.SkipTest(f"Connection error: {exc}") from exc

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        """POST JSON payload and return (status_code, body)."""
        import urllib.request

        url = f"{self.BASE}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": os.environ.get("API_KEY") or "test-key",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise unittest.SkipTest(f"Connection error: {exc}") from exc

    # ── GET /analytics/performance/rolling ────────────────────────────────────

    def test_rolling_performance(self) -> None:
        """GET /analytics/performance/rolling?days=30 must return HTTP 200 with 'days' field."""
        try:
            status, data = self._get("/analytics/performance/rolling", {"days": 30})
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertIn("days", data, f"Response missing 'days' field. Body: {data}")

    # ── GET /portfolio/stats/session-today ────────────────────────────────────

    def test_session_today(self) -> None:
        """GET /portfolio/stats/session-today must return HTTP 200 with non-empty JSON."""
        try:
            status, data = self._get("/portfolio/stats/session-today")
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertGreater(len(data), 0, "Response body must not be empty")

    # ── GET /alerts/history ───────────────────────────────────────────────────

    def test_alerts_history(self) -> None:
        """GET /alerts/history?limit=10 must return HTTP 200 with an 'alerts' list."""
        try:
            status, data = self._get("/alerts/history", {"limit": 10})
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertIn("alerts", data, f"Response missing 'alerts' field. Body: {data}")

    # ── GET /alerts/stats ─────────────────────────────────────────────────────

    def test_alerts_stats(self) -> None:
        """GET /alerts/stats must return HTTP 200 with 'stats' and 'total' fields."""
        try:
            status, data = self._get("/alerts/stats")
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertIn("stats", data, f"Response missing 'stats' field. Body: {data}")
        self.assertIn("total", data, f"Response missing 'total' field. Body: {data}")

    # ── GET /system/preflight ─────────────────────────────────────────────────

    def test_system_preflight(self) -> None:
        """GET /system/preflight must return HTTP 200 with a non-empty JSON body."""
        try:
            status, data = self._get("/system/preflight")
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertGreater(len(data), 0, "Preflight response body must not be empty")

    # ── GET /portfolio/stats/streaks ──────────────────────────────────────────

    def test_streak_stats(self) -> None:
        """GET /portfolio/stats/streaks must return HTTP 200 with streak fields."""
        try:
            status, data = self._get("/portfolio/stats/streaks")
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, "Response must be a JSON object")
        self.assertGreater(len(data), 0, "Streak response body must not be empty")

    # ── POST /portfolio/import/trades — RETIRED (D3-02) ────────────────────────
    # Silently discarded every imported row (INSERT OR IGNORE swallowed a NOT
    # NULL violation on idempotency_key) while reporting HTTP 200. No live
    # caller found; now always returns 410 regardless of payload shape.

    def test_import_trades_empty(self) -> None:
        """POST /portfolio/import/trades — retired, must return HTTP 410 even for an empty list."""
        try:
            status, data = self._post("/portfolio/import/trades", {"trades": []})
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 410, f"Expected 410 (retired), got {status}. Body: {data}")

    def test_import_trades_single(self) -> None:
        """POST /portfolio/import/trades — retired, must return HTTP 410 and write nothing."""
        trade = {
            "trade_id": "test-import-single-fixture-001",
            "symbol": "TEST",
            "action": "LONG",
            "entry_price": 5000.0,
            "exit_price": 5010.0,
            "quantity": 1,
            "pnl": 50.0,
            "entry_time": "2026-03-01T09:30:00Z",
            "exit_time": "2026-03-01T10:00:00Z",
        }
        try:
            status, data = self._post("/portfolio/import/trades", {"trades": [trade]})
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 410, f"Expected 410 (retired), got {status}. Body: {data}")

    def test_import_trades_bad_body(self) -> None:
        """POST /portfolio/import/trades — retired, returns HTTP 410 regardless of body shape."""
        try:
            status, data = self._post("/portfolio/import/trades", {"trades": "not-a-list"})
        except ConnectionError as exc:
            raise unittest.SkipTest(f"Engine not reachable: {exc}") from exc
        self.assertEqual(status, 410, f"Expected 410 (retired), got {status}. Body: {data}")


# ===========================================================================
# TestSession4ExtendedEndpoints
# ===========================================================================


class TestSession4ExtendedEndpoints(unittest.TestCase):
    """Tests for Session 4 extended endpoints (analytics, weekly, notifications).

    All tests are skipped automatically when the engine is not running.
    Start the engine with:  cd engine && uvicorn main:app --port 8010
    """

    BASE = _ENGINE_BASE

    def _get(self, path: str, params: dict | None = None) -> tuple[int, dict]:
        """GET the given path (with optional query params) and return (status_code, body)."""
        from urllib.parse import urlencode

        url = f"{self.BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header("X-API-Key", os.environ.get("API_KEY") or "test-key")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise unittest.SkipTest(f"Connection error: {exc}") from exc

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        """POST JSON payload and return (status_code, body)."""
        import urllib.request

        url = f"{self.BASE}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": os.environ.get("API_KEY") or "test-key",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise unittest.SkipTest(f"Connection error: {exc}") from exc

    @classmethod
    def setUpClass(cls) -> None:
        if not _session4_api_ready():
            raise unittest.SkipTest(
                "Session 4 API not deployed — see live_engine_probe.session4_api_ready"
            )

    # ── GET /analytics/trades/by-day ──────────────────────────────────────────

    def test_trades_by_day(self) -> None:
        """GET /analytics/trades/by-day must return HTTP 200 with a 'days' field."""
        status, data = self._get("/analytics/trades/by-day")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("days", data, f"Response missing 'days' field. Body: {data}")

    # ── GET /analytics/trades/by-symbol ───────────────────────────────────────

    def test_trades_by_symbol(self) -> None:
        """GET /analytics/trades/by-symbol must return HTTP 200 with a 'symbols' field."""
        status, data = self._get("/analytics/trades/by-symbol")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("symbols", data, f"Response missing 'symbols' field. Body: {data}")

    # ── GET /analytics/trades/by-hour ─────────────────────────────────────────

    def test_trades_by_hour(self) -> None:
        """GET /analytics/trades/by-hour must return HTTP 200 with an 'hours' field."""
        status, data = self._get("/analytics/trades/by-hour")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("hours", data, f"Response missing 'hours' field. Body: {data}")

    # ── GET /portfolio/stats/weekly ───────────────────────────────────────────

    def test_weekly_stats(self) -> None:
        """GET /portfolio/stats/weekly must return HTTP 200 with total_trades, win_rate, and period='7d'."""
        status, data = self._get("/portfolio/stats/weekly")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("total_trades", data, f"Response missing 'total_trades' field. Body: {data}")
        self.assertIn("win_rate", data, f"Response missing 'win_rate' field. Body: {data}")
        self.assertEqual(data.get("period"), "7d", f"Expected period='7d'. Body: {data}")

    # ── GET /portfolio/stats/commissions ──────────────────────────────────────

    def test_commissions(self) -> None:
        """GET /portfolio/stats/commissions must return HTTP 200 with 'total_commissions' field."""
        status, data = self._get("/portfolio/stats/commissions")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn(
            "total_commissions",
            data,
            f"Response missing 'total_commissions' field. Body: {data}",
        )

    # ── GET /watchlist/scan ───────────────────────────────────────────────────

    def test_watchlist_scan(self) -> None:
        """GET /watchlist/scan?symbols=MES,MNQ must return HTTP 200 with a 'symbols' field."""
        status, data = self._get("/watchlist/scan", {"symbols": "MES,MNQ"})
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("symbols", data, f"Response missing 'symbols' field. Body: {data}")

    # ── POST /portfolio/import/trades — over-limit, RETIRED (D3-02) ─────────

    def test_import_trades_over_limit(self) -> None:
        """POST /portfolio/import/trades — retired, returns HTTP 410 even for an over-limit payload."""
        status, data = self._post("/portfolio/import/trades", {"trades": [{}] * 1001})
        self.assertEqual(
            status,
            410,
            f"Expected 410 (retired), got {status}. Body: {data}",
        )

    # ── POST /notifications/whatsapp/test ─────────────────────────────────────

    def test_whatsapp_test_notification(self) -> None:
        """POST /notifications/whatsapp/test must return HTTP 200 with 'sent' and 'timestamp' fields."""
        status, data = self._post("/notifications/whatsapp/test", {})
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("sent", data, f"Response missing 'sent' field. Body: {data}")
        self.assertIn("timestamp", data, f"Response missing 'timestamp' field. Body: {data}")


# ===========================================================================
# TestSession4ContinuationEndpoints
# ===========================================================================


class TestSession4ContinuationEndpoints(unittest.TestCase):
    """Tests for Session 4 continuation endpoints.

    All tests are skipped automatically when the engine is not running.
    Start the engine with:  cd engine && uvicorn main:app --port 8010
    """

    BASE_URL = _ENGINE_BASE

    @classmethod
    def setUpClass(cls) -> None:
        if not _session4_api_ready():
            raise unittest.SkipTest(
                "Session 4 API not deployed — see live_engine_probe.session4_api_ready"
            )

    def _get(self, path: str) -> tuple[int, dict]:
        """GET path and return (status_code, body)."""
        import json as _json

        req = urllib.request.Request(f"{self.BASE_URL}{path}")
        req.add_header("X-API-Key", os.environ.get("API_KEY") or "test-key")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, _json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                body = _json.loads(exc.read().decode())
            except Exception:
                body = {}
            return exc.code, body
        except Exception as exc:
            raise unittest.SkipTest(f"Connection error: {exc}") from exc

    # ── GET /analytics/performance/rolling?days=7 ─────────────────────────────

    def test_rolling_performance_7d(self) -> None:
        """GET /analytics/performance/rolling?days=7 returns valid structure."""
        status, data = self._get("/analytics/performance/rolling?days=7")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, f"Expected dict response. Body: {data}")

    # ── GET /analytics/performance/rolling?days=30 ────────────────────────────

    def test_rolling_performance_30d(self) -> None:
        """GET /analytics/performance/rolling?days=30 returns valid structure."""
        status, data = self._get("/analytics/performance/rolling?days=30")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, f"Expected dict response. Body: {data}")

    # ── GET /analytics/performance/rolling?days=0 ─────────────────────────────

    def test_rolling_performance_invalid_days(self) -> None:
        """GET /analytics/performance/rolling?days=0 should return error or empty dict."""
        status, data = self._get("/analytics/performance/rolling?days=0")
        self.assertIn(
            status,
            [200, 400, 422],
            f"Expected 200/400/422 for days=0, got {status}. Body: {data}",
        )

    # ── GET /portfolio/stats/weekly ───────────────────────────────────────────

    def test_portfolio_stats_weekly(self) -> None:
        """GET /portfolio/stats/weekly returns period and trade stats."""
        status, data = self._get("/portfolio/stats/weekly")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("period", data, f"Response missing 'period' field. Body: {data}")
        self.assertEqual(data.get("period"), "7d", f"Expected period='7d'. Body: {data}")
        self.assertIn("total_trades", data, f"Response missing 'total_trades' field. Body: {data}")
        self.assertIn("win_rate", data, f"Response missing 'win_rate' field. Body: {data}")

    # ── GET /analytics/trades/by-hour ─────────────────────────────────────────

    def test_analytics_trades_by_hour(self) -> None:
        """GET /analytics/trades/by-hour returns hours list."""
        status, data = self._get("/analytics/trades/by-hour")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("hours", data, f"Response missing 'hours' field. Body: {data}")
        self.assertIsInstance(data["hours"], list, f"Expected 'hours' to be a list. Body: {data}")

    # ── GET /market/session ───────────────────────────────────────────────────

    def test_market_session(self) -> None:
        """GET /market/session returns session info."""
        status, data = self._get("/market/session")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("session", data, f"Response missing 'session' field. Body: {data}")

    # ── GET /position-sizing/calculate ────────────────────────────────────────

    def test_position_sizing_calculate(self) -> None:
        """GET /position-sizing/calculate returns sizing info."""
        status, data = self._get("/position-sizing/calculate")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIsInstance(data, dict, f"Expected dict response. Body: {data}")

    # ── GET /validation/readiness-check ───────────────────────────────────────

    def test_validation_readiness_check(self) -> None:
        """GET /validation/readiness-check returns criteria list."""
        status, data = self._get("/validation/readiness-check")
        self.assertEqual(status, 200, f"Expected 200, got {status}. Body: {data}")
        self.assertIn("criteria", data, f"Response missing criteria: {data}")
