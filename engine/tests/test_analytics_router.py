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


class TestAgentWeightsEndpoint:
    """GET /analytics/agent-weights -- live_weight must mirror what debate.py
    actually applies (get_weights_by_regime when a regime is known, load_weights()
    otherwise), not a freshly-recomputed all-regime value that can silently
    diverge from the live path (Codex review finding, PR #357)."""

    def test_no_regime_uses_load_weights(self, client):
        """Without a regime, live_weight must come from load_weights() -- the
        exact function debate.py calls in its no-regime branch."""
        resp = client.get("/analytics/agent-weights")
        assert resp.status_code == 200
        body = resp.json()
        assert body["regime"] is None
        assert "load_weights" in body["weights_source"]
        # agent_weights.json is never written by anything in this codebase
        # (grep confirms save_weights() has no callers), so on a fresh
        # environment this must be false, not silently absent from the response.
        assert "weights_file_exists" in body

    def test_with_regime_uses_get_weights_by_regime(self, client):
        """With a regime, live_weight must come from get_weights_by_regime(regime)
        -- the exact function debate.py calls in its regime-conditional branch."""
        resp = client.get("/analytics/agent-weights?regime=TRENDING_BULL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["regime"] == "TRENDING_BULL"
        assert "get_weights_by_regime" in body["weights_source"]

    def test_live_and_recomputed_weight_are_both_present_and_distinct_fields(self, client):
        """Regression: the response must never conflate the live-applied weight
        with the freshly-recomputed diagnostic one under a single ambiguous field."""
        resp = client.get("/analytics/agent-weights")
        assert resp.status_code == 200
        body = resp.json()
        for _agent, entry in body["per_agent"].items():
            assert "live_weight" in entry
            assert "recomputed_weight" in entry


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
        import json as _json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from agents.post_mortem import PostTradeAnalyzer
        from database.manager import DatabaseManager
        from llm.client import LLMCallResult

        db = DatabaseManager(str(tmp_path / "post_mortem_populated.db"))
        db.initialize()
        mock_get_db.return_value = db

        result = LLMCallResult(
            success=True,
            model="test-model",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            retries=0,
            content=_json.dumps({"analysis": "test analysis", "lesson": "test lesson"}),
        )
        llm = SimpleNamespace(call=AsyncMock(return_value=result))
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
        import json as _json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from agents.post_mortem import PostTradeAnalyzer
        from database.manager import DatabaseManager
        from llm.client import LLMCallResult

        db = DatabaseManager(str(tmp_path / "post_mortem_filter.db"))
        db.initialize()
        mock_get_db.return_value = db

        result = LLMCallResult(
            success=True,
            model="test-model",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            retries=0,
            content=_json.dumps({"analysis": "a", "lesson": "l"}),
        )
        llm = SimpleNamespace(call=AsyncMock(return_value=result))
        analyzer = PostTradeAnalyzer(db_manager=db, llm_client=llm)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(analyzer.analyze_trade("T-A", {"symbol": "MGC", "pnl": 1.0}, {}))
        loop.run_until_complete(analyzer.analyze_trade("T-B", {"symbol": "MES", "pnl": 2.0}, {}))

        resp = client.get("/analytics/post-mortems?symbol=MES")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["entries"][0]["trade_id"] == "T-B"


class TestRegimeV2Endpoint:
    """GET /analytics/regime-v2/{symbol} -- the classifier pipeline.py actually routes on."""

    @staticmethod
    def _synthetic_bars(n: int = 80):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        close = 100 + np.cumsum(rng.normal(0, 0.5, n))
        return pd.DataFrame(
            {
                "open": close,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": rng.integers(100, 1000, n),
            }
        )

    def test_returns_real_regime_label(self, client):
        import routers.analytics_router as analytics_router_module

        bars = self._synthetic_bars(80)

        class FakeDataMgr:
            async def get_bars(self, symbol, lookback_days=30, timeframe="1h"):
                return bars

        analytics_router_module._data_mgr = FakeDataMgr()

        resp = client.get("/analytics/regime-v2/mes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "MES"
        assert body["regime"] in ("TREND", "MEANREV", "RANGE", "VOLATILE", "CRISIS")
        # Deterministic rule-based classifier -- must never fabricate a
        # probability vector or claim ground-truth validation that doesn't exist.
        assert body["validated"] is False
        assert body["probability_vector"] is None

    def test_insufficient_bars_returns_unknown(self, client):
        import routers.analytics_router as analytics_router_module

        bars = self._synthetic_bars(5)

        class EmptyDataMgr:
            async def get_bars(self, symbol, lookback_days=30, timeframe="1h"):
                return bars

        analytics_router_module._data_mgr = EmptyDataMgr()

        resp = client.get("/analytics/regime-v2/mnq")
        assert resp.status_code == 200
        body = resp.json()
        assert body["regime"] == "UNKNOWN"
        assert "insufficient" in body["note"]


class TestCorrelationPreviewEndpoint:
    """GET /analytics/correlation-preview -- preview only, never wired to sizing."""

    def test_computes_real_correlation_and_never_double_lists_a_pair(self, client):
        import numpy as np
        import pandas as pd

        import routers.analytics_router as analytics_router_module

        rng = np.random.default_rng(3)
        n = 60
        mes_close = 100 + np.cumsum(rng.normal(0, 0.5, n))
        mgc_close = mes_close * (1 + rng.normal(0, 0.001, n))  # near-identical -> high corr
        mcl_close = 50 + np.cumsum(np.random.default_rng(99).normal(0, 0.5, n))

        bars = {
            "MES": pd.DataFrame({"close": mes_close}),
            "MGC": pd.DataFrame({"close": mgc_close}),
            "MCL": pd.DataFrame({"close": mcl_close}),
        }

        class FakeDataMgr:
            async def get_bars(self, symbol, lookback_days=30, timeframe="1h"):
                return bars.get(symbol)

        analytics_router_module._data_mgr = FakeDataMgr()

        resp = client.get("/analytics/correlation-preview?symbols=MES,MGC,MCL,MNQ")
        assert resp.status_code == 200
        body = resp.json()

        # Never claim this feeds live order sizing -- it doesn't.
        assert body["wired_into_live_sizing"] is False

        assert body["pairs"]["MES/MGC"] > 0.9

        # Regression: a pair that WAS computed must never also appear omitted
        # (caught during manual verification -- alphabetical vs input-order key mismatch).
        computed = set(body["pairs"].keys())
        omitted = set(body["omitted_pairs"])
        assert not (computed & omitted)

        # MNQ has no bar data in this fixture -> every MNQ pair should be omitted.
        assert "MCL/MNQ" in omitted
        assert "MES/MNQ" in omitted
        assert "MGC/MNQ" in omitted

    def test_no_data_manager_returns_empty_not_error(self, client):
        import routers.analytics_router as analytics_router_module

        analytics_router_module._data_mgr = None

        resp = client.get("/analytics/correlation-preview?symbols=MES,MGC")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pairs"] == {}


class TestPipelineFunnel:
    """Pipeline funnel endpoint: shape, monotone stages, and cache-hit path."""

    # fetch_one call order in _compute_pipeline_funnel:
    # runs, signals, approved, executed, filled,
    # human_approved (paq), human_approved2 (pta), human_rejected (pta)
    COUNTS = [100, 10, 5, 3, 3, 2, 1, 4]

    @pytest.fixture(autouse=True)
    def _clear_funnel_cache(self):
        import routers.analytics_router as ar

        ar._funnel_cache.clear()
        yield
        ar._funnel_cache.clear()

    @pytest.fixture
    def mock_db(self):
        import routers.analytics_router as ar

        class _FakeDB:
            def __init__(self, counts):
                self._counts = list(counts)
                self._i = 0

            def fetch_one(self, sql, params=None):
                n = self._counts[self._i] if self._i < len(self._counts) else 0
                self._i += 1
                return {"n": n}

        db = _FakeDB(self.COUNTS)
        ar.set_db_manager(db)
        return db

    def test_funnel_shape_and_rates(self, client, mock_db):
        """GET /analytics/pipeline-funnel returns the monotone 5-stage funnel."""
        resp = client.get("/analytics/pipeline-funnel?days=30")
        assert resp.status_code == 200
        body = resp.json()

        assert body["period"] == "30d"
        assert body["days"] == 30
        assert body["funnel"] == {
            "runs": 100,
            "signals": 10,
            "approved": 5,
            "executed": 3,
            "filled": 3,
        }
        # Monotone: each stage <= previous (runs 100 >= signals 10 >= ... >= filled 3)
        stages = list(body["funnel"].values())
        assert all(stages[i] >= stages[i + 1] for i in range(len(stages) - 1))

        assert body["conversion_rates"]["runs_to_signals"] == 10.0
        assert body["conversion_rates"]["signals_to_approved"] == 50.0
        assert body["conversion_rates"]["approved_to_executed"] == 60.0
        assert body["conversion_rates"]["executed_to_filled"] == 100.0
        assert body["conversion_rates"]["overall_conversion"] == 3.0

        # Human lanes are reported separately, not folded into the chain
        assert body["details"]["human_approved"] == 3
        assert body["details"]["human_rejected"] == 4
        assert body["details"]["cache_hit"] is False

    def test_funnel_cache_hit_returns_200(self, client, mock_db):
        """Regression: second request inside the TTL must NOT 500.

        The cache entry is {"computed_at", "payload"}; the cache-hit path
        previously read cached["details"] (KeyError -> 500) instead of
        cached["payload"]["details"]. Live symptom: first poll OK, every
        repeat poll within 60s returned 500 and the dashboard showed zeros.
        """
        first = client.get("/analytics/pipeline-funnel?days=30")
        assert first.status_code == 200

        second = client.get("/analytics/pipeline-funnel?days=30")
        assert second.status_code == 200
        body = second.json()
        assert body["funnel"]["runs"] == 100
        assert body["details"]["cache_hit"] is True

    def test_funnel_windows_are_independent(self, client, mock_db):
        """30d and 90d cache entries must not collide."""
        r30 = client.get("/analytics/pipeline-funnel?days=30").json()
        r90 = client.get("/analytics/pipeline-funnel?days=90").json()
        assert r30["period"] == "30d"
        assert r90["period"] == "90d"
        assert r30["days"] == 30
        assert r90["days"] == 90
