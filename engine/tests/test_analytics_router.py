"""
JARVIS TRADER — Analytics Router Tests
======================================
HTTP integration tests for analytics endpoints.
Tests GET /analytics/trades, /signal-quality, /performance, and /trades/by-*.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_analytics_router.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set test environment variables BEFORE any imports
test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

# Add engine to path
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.fixture
def mock_trade_data(sample_closed_trades):
    """Mock trade data from conftest (with analytics router additions)."""
    return sample_closed_trades


def _mock_analytics():
    """Mock analytics result."""
    m = MagicMock()
    m.sharpe_ratio, m.profit_factor, m.max_drawdown_pct, m.win_rate = 2.5, 3.0, 0.05, 0.67
    m.expectancy, m.total_trades, m.total_pnl = 8.33, 3, 15.0
    m.avg_win, m.avg_loss, m.best_trade, m.worst_trade = 10.0, 5.0, 10.0, -5.0
    return m


def _mock_signal_metrics():
    """Mock signal metrics."""
    m = MagicMock()
    m.total_signals, m.profitable_signals, m.accuracy = 3, 2, 0.67
    m.avg_signal_to_entry_minutes, m.avg_entry_to_peak_minutes = 5.2, 12.5
    m.avg_pnl_per_signal, m.best_time_of_day, m.worst_time_of_day = 5.0, "14:00", "09:00"
    return m


def _mock_signal_quality_report():
    """Mock signal quality report."""
    metrics = _mock_signal_metrics()
    r = MagicMock()
    r.overall, r.by_symbol, r.by_regime = metrics, {"MCL": metrics}, {"TRENDING_BULL": metrics}
    r.recommendations = ["Increase entry confidence"]
    return r


@pytest.fixture
def client():
    """TestClient wrapping analytics router with rate limiting disabled."""
    import sys

    from slowapi import Limiter

    # Force re-import so @limiter.limit() decorators get patched as no-ops
    for key in list(sys.modules.keys()):
        if "analytics_router" in key:
            del sys.modules[key]

    with patch.object(Limiter, "limit", return_value=lambda f: f):
        from routers.analytics_router import router as analytics_router

    app = FastAPI()
    app.include_router(analytics_router)
    return TestClient(app, raise_server_exceptions=True)


class TestAnalyticsRouter:
    """Analytics router tests."""

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.trade_analytics.calculate_analytics")
    def test_get_trades_analytics_returns_200(
        self, mock_calc, mock_get_trades, client, mock_trade_data
    ):
        """GET /analytics/trades returns 200 with schema."""
        mock_get_trades.return_value = mock_trade_data
        mock_calc.return_value = _mock_analytics()

        resp = client.get("/analytics/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sharpe_ratio"] == 2.5
        assert data["total_trades"] == 3

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.trade_analytics.calculate_analytics")
    def test_get_trades_analytics_has_all_fields(
        self, mock_calc, mock_get_trades, client, mock_trade_data
    ):
        """Response has all required fields."""
        mock_get_trades.return_value = mock_trade_data
        mock_calc.return_value = _mock_analytics()

        data = client.get("/analytics/trades").json()
        required = [
            "sharpe_ratio",
            "profit_factor",
            "max_drawdown_pct",
            "win_rate",
            "expectancy",
            "total_trades",
            "total_pnl",
            "avg_win",
            "avg_loss",
            "best_trade",
            "worst_trade",
        ]
        for field in required:
            assert field in data

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.trade_analytics.calculate_analytics")
    def test_get_trades_analytics_error(self, mock_calc, mock_get_trades, client):
        """GET /analytics/trades returns 500 on error."""
        mock_get_trades.return_value = []
        mock_calc.side_effect = ValueError("Error")

        resp = client.get("/analytics/trades")
        assert resp.status_code == 500

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.signal_quality.analyze_signal_quality")
    def test_get_signal_quality_returns_200(
        self, mock_analyze, mock_get_trades, client, mock_trade_data
    ):
        """GET /analytics/signal-quality returns 200."""
        mock_get_trades.return_value = mock_trade_data
        mock_analyze.return_value = _mock_signal_quality_report()

        resp = client.get("/analytics/signal-quality")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data
        assert "by_symbol" in data
        assert "recommendations" in data

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.signal_quality.analyze_signal_quality")
    def test_get_signal_quality_with_filters(
        self, mock_analyze, mock_get_trades, client, mock_trade_data
    ):
        """GET /analytics/signal-quality filters by symbol/dates."""
        mock_get_trades.return_value = mock_trade_data
        mock_analyze.return_value = _mock_signal_quality_report()

        resp = client.get("/analytics/signal-quality?symbol=MCL&start_date=2026-03-01")
        assert resp.status_code == 200

    @patch("routers.analytics_router._get_all_trades")
    @patch("analytics.signal_quality.analyze_signal_quality")
    def test_get_signal_quality_error(self, mock_analyze, mock_get_trades, client):
        """GET /analytics/signal-quality returns 500 on error."""
        mock_get_trades.return_value = []
        mock_analyze.side_effect = RuntimeError("Error")

        resp = client.get("/analytics/signal-quality")
        assert resp.status_code == 500

    @patch("routers.analytics_router._get_db")
    @patch("analytics.trade_analytics.calculate_analytics")
    def test_get_performance_returns_200(
        self, mock_calc, mock_router_get_db, client, mock_trade_data
    ):
        """GET /analytics/performance returns 200."""
        mock_db = MagicMock()
        mock_db.get_closed_trades.return_value = [{"pnl": 10.0}, {"pnl": -5.0}]
        mock_router_get_db.return_value = mock_db
        mock_calc.return_value = _mock_analytics()

        resp = client.get("/analytics/performance")
        assert resp.status_code == 200

    @patch("analytics.performance.PerformanceCalculator")
    @patch("routers.analytics_router._get_db")
    def test_validation_report_returns_200(self, mock_get_db, mock_pc_cls, client, mock_trade_data):
        """GET /analytics/validation-report returns structured validation payload."""
        mock_get_db.return_value = MagicMock()
        inst = MagicMock()
        inst.get_validation_report.return_value = {
            "status": "INSUFFICIENT_DATA",
            "metrics": {},
            "thresholds": {
                "profit_factor": 2.0,
                "sharpe_ratio": 1.5,
                "min_trades_required": 10,
            },
            "recommendation": "Collect more trades.",
        }
        mock_pc_cls.return_value = inst

        resp = client.get("/analytics/validation-report")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "INSUFFICIENT_DATA"
        assert "metrics" in body and "recommendation" in body

    @patch("routers.analytics_router._get_db")
    def test_get_trades_by_breakouts(self, mock_get_db, client, mock_trade_data):
        """GET /analytics/trades/by-* endpoints return valid responses."""
        import threading

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db = MagicMock()
        mock_db._lock = threading.Lock()
        mock_db._connect.return_value = mock_conn

        mock_get_db.return_value = mock_db

        for endpoint in [
            "/analytics/trades/by-day",
            "/analytics/trades/by-symbol",
            "/analytics/trades/by-hour",
        ]:
            resp = client.get(endpoint)
            assert resp.status_code == 200


class TestPostMortemsEndpoint:
    """GET /analytics/post-mortems — real DatabaseManager round trip via HTTP."""

    @patch("routers.analytics_router._get_db")
    def test_empty_table_returns_200_not_500(self, mock_get_db, client, tmp_path):
        """Table doesn't exist yet (no post-mortem ever written) -> empty list, not an error."""
        from database.manager import DatabaseManager

        db = DatabaseManager(str(tmp_path / "post_mortem_empty.db"))
        db.initialize()
        mock_get_db.return_value = db

        resp = client.get("/analytics/post-mortems")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert body["total"] == 0

    @patch("routers.analytics_router._get_db")
    def test_populated_table_returns_rows(self, mock_get_db, client, tmp_path):
        """A real PostTradeAnalyzer-written row is returned, most-recent-first."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        import json as _json

        from agents.post_mortem import PostTradeAnalyzer
        from database.manager import DatabaseManager

        db = DatabaseManager(str(tmp_path / "post_mortem_populated.db"))
        db.initialize()
        mock_get_db.return_value = db

        msg = SimpleNamespace(
            content=[SimpleNamespace(text=_json.dumps({"analysis": "test analysis", "lesson": "test lesson"}))]
        )
        llm = SimpleNamespace(client=SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=msg))))
        analyzer = PostTradeAnalyzer(db_manager=db, llm_client=llm)
        asyncio.get_event_loop().run_until_complete(
            analyzer.analyze_trade("T-42", {"symbol": "MGC", "pnl": 88.5}, {})
        )

        resp = client.get("/analytics/post-mortems")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["entries"][0]["trade_id"] == "T-42"
        assert body["entries"][0]["symbol"] == "MGC"
        assert body["entries"][0]["lesson"] == "test lesson"

    @patch("routers.analytics_router._get_db")
    def test_symbol_filter(self, mock_get_db, client, tmp_path):
        """?symbol= filters to only that symbol's rows."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        import json as _json

        from agents.post_mortem import PostTradeAnalyzer
        from database.manager import DatabaseManager

        db = DatabaseManager(str(tmp_path / "post_mortem_filter.db"))
        db.initialize()
        mock_get_db.return_value = db

        msg = SimpleNamespace(
            content=[SimpleNamespace(text=_json.dumps({"analysis": "a", "lesson": "l"}))]
        )
        llm = SimpleNamespace(client=SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=msg))))
        analyzer = PostTradeAnalyzer(db_manager=db, llm_client=llm)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(analyzer.analyze_trade("T-A", {"symbol": "MGC", "pnl": 1.0}, {}))
        loop.run_until_complete(analyzer.analyze_trade("T-B", {"symbol": "MES", "pnl": 2.0}, {}))

        resp = client.get("/analytics/post-mortems?symbol=MES")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["entries"][0]["trade_id"] == "T-B"
