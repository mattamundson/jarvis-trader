"""
Session 4 offline strict tests — TestClient equivalents that assert HTTP 200.

All 9 tests mirror TestSession4Endpoints in test_integration.py but use
FastAPI TestClient (no live engine required) and assert status_code == 200
strictly (not 200 or 503).

Dependencies (db_manager, safety_layer) are injected as mocks backed by a
real in-memory SQLite database so endpoints execute fully without error.

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_session4_offline_strict.py -v
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.modules mocking — MUST happen at module level before importing main
# ---------------------------------------------------------------------------

_MODULES_TO_MOCK = [
    "data.market_data",
    "risk.safety_layer",
    "risk.pnl_monitor",
    "agents.bear_researcher",
    "agents.bull_researcher",
    "agents.debate",
    "agents.fund_manager",
    "agents.fundamental_analyst",
    "agents.news_analyst",
    "agents.risk_manager",
    "agents.social_analyst",
    "agents.technical_analyst",
    "agents.thinkscript_generator",
    "agents.trader",
    "portfolio.tracker",
    "database.schema",
    "schedulers.eod_scheduler",
    "routers.journal_router",
    "routers.webhook_router",
    "execution.ib_order_manager",
    "notifications.whatsapp",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers.cron",
]

_saved_modules: dict = {}
for _mod_name in _MODULES_TO_MOCK:
    _saved_modules[_mod_name] = sys.modules.get(_mod_name)
    sys.modules[_mod_name] = mock.MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from config import settings  # noqa: E402  (must come after mocks)

app = main.app

# Restore real modules after app is imported
for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

# Clean parent module attributes for dotted names
for _mod_name in _MODULES_TO_MOCK:
    if "." in _mod_name:
        _parent, _attr = _mod_name.rsplit(".", 1)
        _parent_mod = sys.modules.get(_parent)
        if _parent_mod is not None and hasattr(_parent_mod, _attr):
            _original = _saved_modules.get(_mod_name)
            if _original is not None:
                # Restore the real submodule reference (not just delete it) --
                # a later-collected test file's string-based monkeypatch/mock
                # target (e.g. "notifications.whatsapp.send_x") resolves via
                # this attribute, not just via sys.modules.
                setattr(_parent_mod, _attr, _original)
            else:
                try:
                    delattr(_parent_mod, _attr)
                except AttributeError:
                    pass

# ---------------------------------------------------------------------------
# Build an in-memory SQLite DB with the required schema
# ---------------------------------------------------------------------------

_DB_PATH = ":memory:"


def _create_test_db() -> sqlite3.Connection:
    """Create an in-memory SQLite connection with the required tables."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            trade_id    TEXT PRIMARY KEY,
            symbol      TEXT,
            side        TEXT,
            entry_price REAL,
            exit_price  REAL,
            quantity    INTEGER,
            pnl         REAL,
            status      TEXT DEFAULT 'open',
            entry_time  TEXT,
            exit_time   TEXT,
            strategy_params TEXT,
            notes       TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type  TEXT,
            status      TEXT,
            message     TEXT,
            created_at  TEXT
        )
    """
    )
    conn.commit()
    return conn


# Persistent in-memory connection (keep alive for the test session)
_CONN = _create_test_db()

# Temp file path for endpoints that call sqlite3.connect(str(db_manager._db_path))
import os as _os
import tempfile as _tempfile

_TMP_DB_FILE = _tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB_FILE.close()
_TMP_DB_PATH = Path(_TMP_DB_FILE.name)

# Initialise the temp file DB with the same schema
_tmp_conn = sqlite3.connect(str(_TMP_DB_PATH))
_tmp_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
        trade_id    TEXT PRIMARY KEY,
        symbol      TEXT,
        side        TEXT,
        entry_price REAL,
        exit_price  REAL,
        quantity    INTEGER,
        pnl         REAL,
        status      TEXT DEFAULT 'open',
        entry_time  TEXT,
        exit_time   TEXT,
        strategy_params TEXT,
        notes       TEXT
    )
"""
)
_tmp_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS alert_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type  TEXT,
        status      TEXT,
        message     TEXT,
        created_at  TEXT
    )
"""
)
_tmp_conn.commit()
_tmp_conn.close()

# ---------------------------------------------------------------------------
# Build mock db_manager and safety_layer
# ---------------------------------------------------------------------------


class _FakeDbManager:
    """Minimal db_manager stand-in backed by the temp SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()

    def get_closed_trades(self, limit: int = 10000, symbol: str | None = None) -> list[dict]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE status = 'closed' ORDER BY exit_time ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_alert_history(self, limit: int = 100, alert_type: str | None = None) -> list[dict]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            if alert_type:
                rows = conn.execute(
                    "SELECT * FROM alert_log WHERE alert_type = ? ORDER BY id DESC LIMIT ?",
                    (alert_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_trade_history(self, limit: int = 100) -> list[dict]:
        return self.get_closed_trades(limit=limit)

    def _connect(self) -> sqlite3.Connection:
        """Open and return a new connection (with row_factory set)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn


class _FakeSafetyLayer:
    """Minimal safety_layer stand-in."""

    _kill_switch_active: bool = False

    def check_circuit_breakers(self) -> dict:
        return {"daily_limit_breached": False, "drawdown_breached": False}

    def get_status(self) -> dict:
        return {"kill_switch": False, "circuit_breakers": {}}


_fake_db = _FakeDbManager(_TMP_DB_PATH)
_fake_safety = _FakeSafetyLayer()

# ---------------------------------------------------------------------------
# Inject mocks into main module globals
# ---------------------------------------------------------------------------

main.db_manager = _fake_db
main.safety_layer = _fake_safety

# Inject into routers that maintain their own module-level db_manager reference.
# These are set by main.py's lifespan startup which doesn't run under TestClient.
from routers import alerts_router as _alerts_router  # noqa: E402
from routers import analytics_router as _analytics_router  # noqa: E402
from routers import portfolio_router as _portfolio_router  # noqa: E402

_analytics_router.set_db_manager(_fake_db)
_alerts_router.inject_dependencies(db_manager=_fake_db)
# portfolio_router uses inject_dependencies(pt, dbm, dm=None, safety_layer=None)
_portfolio_router.inject_dependencies(
    pt=mock.MagicMock(),
    dbm=_fake_db,
    dm=None,
    safety_layer=_fake_safety,
)

# ---------------------------------------------------------------------------
# Shared client + auth header
# ---------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)
_AUTH = {"X-API-Key": settings.API_KEY}


# ===========================================================================
# TestSession4OfflineStrict — 200-strict equivalents of TestSession4Endpoints
# ===========================================================================


class TestSession4OfflineStrict:
    """Offline strict tests: every endpoint MUST return HTTP 200."""

    def setup_method(self, _method) -> None:
        """Re-inject fake dependencies before each test.

        Module-level injection can be overwritten by other test files whose
        module-level code runs during pytest collection (alphabetically after
        this file).  Re-injecting here makes each test independent of
        cross-file ordering contamination.
        """
        _analytics_router.set_db_manager(_fake_db)
        _alerts_router.inject_dependencies(db_manager=_fake_db)
        _portfolio_router.inject_dependencies(
            pt=mock.MagicMock(),
            dbm=_fake_db,
            dm=None,
            safety_layer=_fake_safety,
        )

    # ── GET /analytics/performance/rolling ────────────────────────────────

    def test_rolling_performance(self) -> None:
        """GET /analytics/performance/rolling?days=30 must return 200 with 'days' field."""
        r = client.get("/analytics/performance/rolling", params={"days": 30}, headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert "days" in body, f"Response missing 'days' field. Body: {body}"

    # ── GET /portfolio/stats/session-today ────────────────────────────────

    def test_session_today(self) -> None:
        """GET /portfolio/stats/session-today must return 200 with non-empty JSON."""
        r = client.get("/portfolio/stats/session-today", headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert len(body) > 0, "Response body must not be empty"

    # ── GET /alerts/history ───────────────────────────────────────────────

    def test_alerts_history(self) -> None:
        """GET /alerts/history?limit=10 must return 200 with an 'alerts' list."""
        r = client.get("/alerts/history", params={"limit": 10}, headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert "alerts" in body, f"Response missing 'alerts' field. Body: {body}"

    # ── GET /alerts/stats ─────────────────────────────────────────────────

    def test_alerts_stats(self) -> None:
        """GET /alerts/stats must return 200 with 'stats' and 'total' fields."""
        r = client.get("/alerts/stats", headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert "stats" in body, f"Response missing 'stats' field. Body: {body}"
        assert "total" in body, f"Response missing 'total' field. Body: {body}"

    # ── GET /system/preflight ─────────────────────────────────────────────

    def test_system_preflight(self) -> None:
        """GET /system/preflight must return 200 with a non-empty JSON body."""
        r = client.get("/system/preflight", headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert len(body) > 0, "Preflight response body must not be empty"

    # ── GET /portfolio/stats/streaks ──────────────────────────────────────

    def test_streak_stats(self) -> None:
        """GET /portfolio/stats/streaks must return 200 with streak fields."""
        r = client.get("/portfolio/stats/streaks", headers=_AUTH)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}. Body: {r.text}"
        body = r.json()
        assert isinstance(body, dict), "Response must be a JSON object"
        assert len(body) > 0, "Streak response body must not be empty"

    # ── POST /portfolio/import/trades — RETIRED (D3-02) ────────────────────
    # Silently discarded every imported row (INSERT OR IGNORE swallowed a NOT
    # NULL violation on idempotency_key) while reporting HTTP 200. No live
    # caller found; now always returns 410 regardless of payload shape.

    def test_import_trades_empty(self) -> None:
        """POST /portfolio/import/trades — retired, must return 410 even for an empty list."""
        r = client.post("/portfolio/import/trades", json={"trades": []}, headers=_AUTH)
        assert r.status_code == 410, f"Expected 410 (retired), got {r.status_code}. Body: {r.text}"

    def test_import_trades_single(self) -> None:
        """POST /portfolio/import/trades — retired, must return 410 and write nothing."""
        trade = {
            "trade_id": "test-offline-strict-single-001",
            "symbol": "TEST",
            "action": "LONG",
            "entry_price": 5000.0,
            "exit_price": 5010.0,
            "quantity": 1,
            "pnl": 50.0,
            "entry_time": "2026-03-01T09:30:00Z",
            "exit_time": "2026-03-01T10:00:00Z",
        }
        r = client.post("/portfolio/import/trades", json={"trades": [trade]}, headers=_AUTH)
        assert r.status_code == 410, f"Expected 410 (retired), got {r.status_code}. Body: {r.text}"

    def test_import_trades_bad_body(self) -> None:
        """POST /portfolio/import/trades — retired, returns 410 regardless of body shape."""
        r = client.post("/portfolio/import/trades", json={"trades": "not-a-list"}, headers=_AUTH)
        assert r.status_code == 410, f"Expected 410 (retired), got {r.status_code}. Body: {r.text}"
