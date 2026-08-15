"""
Session 4 extended offline tests — TestClient equivalents for TestSession4ExtendedEndpoints.

These tests exercise all Session 4 extended endpoints via FastAPI TestClient (no live
engine required).  All tests assert HTTP 200 (or 400 for the over-limit validation test)
by mocking db_manager and related dependencies.

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_session4_extended_offline.py -v

See also: tests/test_session4_contract.py — looser contract tests that accept 200 or 503.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# sys.modules mocking — MUST happen at module level before importing main.
# Copied verbatim from test_session4_contract.py.
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

import main as main_mod  # noqa: E402
from config import settings  # noqa: E402  (must come after mocks)
from main import app  # noqa: E402

# Restore real modules after app is imported so other test files get genuine
# implementations (prevents cross-test contamination).
for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

# Clean parent module attributes for dotted names (same fix as test_auth_and_rate_limit).
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
# Shared client + auth header
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

import routers.analytics_router as _analytics_router_mod  # noqa: E402
import routers.portfolio_router as _portfolio_router_mod  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_AUTH = {"X-API-Key": settings.API_KEY}


# ---------------------------------------------------------------------------
# Helper: build a real SQLite temp database + a lightweight db-manager shim
# that satisfies both main.py routes (use _lock + _db_path) and
# analytics_router.py routes (use _lock + _connect()).
# ---------------------------------------------------------------------------


class _FakeDbManager:
    """
    Minimal DatabaseManager stand-in backed by a real SQLite temp file.

    Provides:
      - _lock            — threading.Lock()
      - _db_path         — Path to temp .db file
      - _connect()       — returns sqlite3.Connection with row_factory=sqlite3.Row
      - get_trade_history() — returns []
    """

    def __init__(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._db_path = Path(tmp.name)
        self._lock = threading.Lock()

        # Bootstrap the schema.
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                trade_id    TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL DEFAULT 'LONG',
                entry_price REAL,
                exit_price  REAL,
                quantity    INTEGER DEFAULT 1,
                pnl         REAL DEFAULT 0.0,
                status      TEXT DEFAULT 'OPEN',
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
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Open and return a new connection (with row_factory set)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_trade_history(self, limit: int = 10000, **kwargs):  # noqa: ANN001
        return []


# ---------------------------------------------------------------------------
# TestSession4ExtendedOffline
# ---------------------------------------------------------------------------


class TestSession4ExtendedOffline(unittest.TestCase):
    """
    Offline equivalents for TestSession4ExtendedEndpoints in test_integration.py.

    Each test mocks main_mod.db_manager with a real SQLite-backed mock so that
    the endpoint handler can execute its SQL without a live database.  All
    tests assert HTTP 200 (except test_import_trades_over_limit which asserts 400).
    """

    def setUp(self) -> None:
        """Create a fresh db_manager mock for each test."""
        self._db_mock = _FakeDbManager()

    # ── GET /analytics/trades/by-day ──────────────────────────────────────────

    def test_trades_by_day(self) -> None:
        """GET /analytics/trades/by-day must return HTTP 200 with a 'days' field.

        The route is served by analytics_router (prefix=/analytics) which uses its own
        _db variable, so we patch both main_mod.db_manager and _analytics_router_mod._db.
        """
        with (
            patch.object(main_mod, "db_manager", self._db_mock),
            patch.object(_analytics_router_mod, "_db", self._db_mock),
        ):
            r = client.get("/analytics/trades/by-day", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("days", body, f"Response missing 'days' field. Body: {body}")

    # ── GET /analytics/trades/by-symbol ───────────────────────────────────────

    def test_trades_by_symbol(self) -> None:
        """GET /analytics/trades/by-symbol must return HTTP 200 with a 'symbols' field.

        Same analytics_router pattern as test_trades_by_day.
        """
        with (
            patch.object(main_mod, "db_manager", self._db_mock),
            patch.object(_analytics_router_mod, "_db", self._db_mock),
        ):
            r = client.get("/analytics/trades/by-symbol", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("symbols", body, f"Response missing 'symbols' field. Body: {body}")

    # ── GET /analytics/trades/by-hour ─────────────────────────────────────────

    def test_trades_by_hour(self) -> None:
        """GET /analytics/trades/by-hour must return HTTP 200 with an 'hours' field."""
        with patch.object(main_mod, "db_manager", self._db_mock):
            r = client.get("/analytics/trades/by-hour", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("hours", body, f"Response missing 'hours' field. Body: {body}")

    # ── GET /portfolio/stats/weekly ───────────────────────────────────────────

    def test_weekly_stats(self) -> None:
        """GET /portfolio/stats/weekly must return HTTP 200 with required fields."""
        with (
            patch.object(main_mod, "db_manager", self._db_mock),
            patch.object(_portfolio_router_mod, "db_manager", self._db_mock),
        ):
            r = client.get("/portfolio/stats/weekly", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("total_trades", body, f"Response missing 'total_trades'. Body: {body}")
        self.assertIn("win_rate", body, f"Response missing 'win_rate'. Body: {body}")
        self.assertEqual(
            body.get("period"),
            "7d",
            f"Expected period='7d'. Body: {body}",
        )

    # ── GET /portfolio/stats/commissions ──────────────────────────────────────

    def test_commissions(self) -> None:
        """GET /portfolio/stats/commissions must return HTTP 200 with 'total_commissions'."""
        with patch.object(main_mod, "db_manager", self._db_mock):
            r = client.get("/portfolio/stats/commissions", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn(
            "total_commissions",
            body,
            f"Response missing 'total_commissions'. Body: {body}",
        )

    # ── GET /watchlist/scan ───────────────────────────────────────────────────

    def test_watchlist_scan(self) -> None:
        """GET /watchlist/scan?symbols=MES,MNQ must return HTTP 200 with a 'symbols' field.

        The /watchlist/scan endpoint imports analytics.mtf_analyzer inside the handler.
        Per-symbol errors are caught and each symbol returns with recommendation='WAIT'.
        The overall response still returns 200 with a 'symbols' list.
        """
        # analytics.mtf_analyzer is not in _MODULES_TO_MOCK so we patch it inline.
        mock_analyze_mtf = MagicMock()

        async def _fake_analyze_mtf(symbol, data_manager):
            raise RuntimeError("No market data in offline test")

        mock_analyze_mtf.side_effect = _fake_analyze_mtf

        with patch.dict(
            sys.modules,
            {"analytics.mtf_analyzer": MagicMock(analyze_mtf=mock_analyze_mtf)},
        ):
            with patch.object(main_mod, "db_manager", self._db_mock):
                r = client.get(
                    "/watchlist/scan",
                    params={"symbols": "MES,MNQ"},
                    headers=_AUTH,
                )
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("symbols", body, f"Response missing 'symbols' field. Body: {body}")

    # ── POST /portfolio/import/trades — over-limit, RETIRED (D3-02) ─────────

    def test_import_trades_over_limit(self) -> None:
        """POST /portfolio/import/trades — retired, returns 410 even for an over-limit payload."""
        with patch.object(main_mod, "db_manager", self._db_mock):
            r = client.post(
                "/portfolio/import/trades",
                json={"trades": [{}] * 1001},
                headers=_AUTH,
            )
        self.assertEqual(
            r.status_code,
            410,
            f"Expected 410 (retired), got {r.status_code}. Body: {r.text}",
        )

    # ── POST /notifications/whatsapp/test ─────────────────────────────────────

    def test_whatsapp_test_notification(self) -> None:
        """POST /notifications/whatsapp/test must return HTTP 200 with 'sent' and 'timestamp'."""
        # The handler does: from notifications.whatsapp import get_notifier
        # We mock that module so get_notifier() returns a notifier with enabled=False,
        # which causes the handler to return the not_configured response (still 200).
        mock_notifier = MagicMock()
        mock_notifier.enabled = False

        mock_whatsapp_module = MagicMock()
        mock_whatsapp_module.get_notifier.return_value = mock_notifier

        with patch.dict(sys.modules, {"notifications.whatsapp": mock_whatsapp_module}):
            with patch.object(main_mod, "db_manager", self._db_mock):
                r = client.post("/notifications/whatsapp/test", headers=_AUTH)
        self.assertEqual(
            r.status_code,
            200,
            f"Expected 200, got {r.status_code}. Body: {r.text}",
        )
        body = r.json()
        self.assertIn("sent", body, f"Response missing 'sent' field. Body: {body}")
        self.assertIn("timestamp", body, f"Response missing 'timestamp' field. Body: {body}")
