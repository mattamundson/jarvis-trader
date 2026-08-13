"""
JARVIS TRADER — Pytest Fixtures
Shared test fixtures for all test modules.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

_tests_dir = Path(__file__).resolve().parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

# Tests run with cwd=engine/ (per testing.md: `cd engine && pytest tests/`), so
# `python -m pytest`'s cwd-on-sys.path behavior already makes engine's own
# top-level modules importable as shortcuts (`from data import ...`, `from
# config import TradingConfig`). Production code (e.g. agents/debate.py's
# `_get_brier_tracker`) additionally tries the absolute `engine.analytics.X`
# form first, falling back to the shortcut on ImportError — several tests
# patch that absolute-path module directly (test_full_brier_loop.py,
# test_calibration_endpoint.py, test_brier_debate_wiring.py) and need it to
# actually resolve. Append (not insert/prepend) so this never shadows the
# engine-relative shortcuts already on sys.path for ambiguous top-level names
# like `data` (this worktree also has an unrelated top-level `data/` dir).
_repo_root = _tests_dir.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.append(str(_repo_root))

# Sanitize SSL_CERT_FILE / SSL_CERT_DIR before any TLS-using import. Anaconda's
# activation hooks set these to paths that may not exist (e.g. forward-slash mix
# `C:\Users\mattm\anaconda3/ssl/cacert.pem` vs the real `Library\ssl\cacert.pem`).
# When the path doesn't exist, urllib/requests/httpx fail with bewildering errors
# (e.g. SSL: CERTIFICATE_VERIFY_FAILED, FileNotFoundError on cert load) — the
# triage agent observed 13 test_market_modules errors collapsing to this cause.
for _cert_var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
    _val = os.environ.get(_cert_var)
    if _val and not Path(_val).exists():
        os.environ.pop(_cert_var, None)

# Read real API_KEY from engine/.env so live integration tests authenticate correctly.
# Falls back to "test-key" if .env is absent (unit tests don't need the real key).
_engine_env = Path(__file__).parent.parent / ".env"
_real_api_key = "test-key"
if _engine_env.exists():
    for _line in _engine_env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if _line.startswith("API_KEY=") and not _line.startswith("#"):
            _real_api_key = _line.split("=", 1)[1].strip()
            break

# API_KEY is always forced from .env (not setdefault) so that live integration tests
# authenticate correctly even when the shell already has API_KEY set to something else.
os.environ["API_KEY"] = _real_api_key

# Disable outbound OpenClaw notifications during pytest runs to prevent
# WhatsApp spam, gateway auth errors, and pending async shutdown noise.
os.environ["TESTING"] = "1"
os.environ["OPENCLAW_ENABLED"] = "false"
os.environ.pop("OPENCLAW_WHATSAPP_TO", None)

# Set remaining test environment variables BEFORE any imports.
# Uses setdefault so shell overrides are respected for non-critical vars.
test_env_vars = {
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

from agents.schemas import (
    EntrySignal,
    FundamentalReport,
    MarketRegime,
    NewsReport,
    SocialReport,
    TechnicalReport,
    TrendDirection,
)
from config import TradingConfig
from risk.safety_layer import SafetyLayer


@pytest.fixture(autouse=True)
def _isolate_bars_db(tmp_path, monkeypatch):
    """Redirect the bars repository's default DB to a per-test temp file.

    save_bars()/load_bars() fall back to the PRODUCTION engine/data/
    jarvis_trader.db when db_path is None. Tests that exercise
    MarketDataManager paths with fixture data (closes ~100.5, source
    'ibkr'/'tv'/'smoke_test') were silently inserting those fixtures into
    the live market_data_bars table — the 2026-06 bar-store contamination
    that poisoned MCL/MES backtests. Forcing the default into tmp_path
    makes the whole class of leaks impossible regardless of which code
    path reaches the repository.
    """
    from data import bars_repository

    monkeypatch.setattr(
        bars_repository, "_DEFAULT_DB_PATH", tmp_path / "test_bars.db"
    )


@pytest.fixture(autouse=True)
def _reset_health_snapshot():
    """Clear the /health single-flight snapshot cache before every test.

    /health serves a cached payload for up to HEALTH_SNAPSHOT_TTL_SEC (1s) to
    collapse the dashboard polling storm. In production that staleness is fine,
    but tests mock health sub-functions and expect the very next /health call to
    reflect them — within the 1s TTL, a prior test's payload would leak and mask
    the mock. Resetting the snapshot per-test makes each /health call recompute.
    """
    try:
        from routers import health_router

        health_router._health_snapshot.update(computed_at=0.0, payload=None)
    except Exception:
        # Router not importable in this test's context — nothing to reset.
        pass
    yield


@pytest.fixture
def mock_settings():
    """Safe test configuration with conservative limits."""
    config = TradingConfig()
    # Override with test-safe defaults
    config.LIVE_TRADING_ENABLED = False
    config.REQUIRE_HUMAN_APPROVAL = True
    # B8 (2026-06-11): TradingConfig() reads the LIVE engine/.env, so the
    # machine's ALLOW_PAPER_SIMULATED_ORDERS=True leaked in and silently
    # bypassed the live-trading gate in 3 SACRED safety tests (the sim path
    # short-circuits _check_gating_conditions to approved). Pin False here;
    # tests exercising the sim path opt in explicitly.
    config.ALLOW_PAPER_SIMULATED_ORDERS = False
    config.MAX_DAILY_LOSS_PCT = 0.02  # -2%
    config.MAX_DRAWDOWN_PCT = 0.10  # -10%
    config.MAX_POSITION_SIZE_PCT = 0.05  # 5% per position
    config.MAX_SINGLE_ORDER_VALUE = 5000.0
    config.MAX_ORDERS_PER_MINUTE = 10
    config.MAX_CONTRACTS_PER_INSTRUMENT = 2
    config.MAX_MARGIN_UTILIZATION = 0.40
    config.PRICE_COLLAR_PCT = 0.05
    config.MAX_CORRELATED_EXPOSURE_PCT = 0.20
    config.MAX_FUTURES_MARGIN_PCT = 0.30  # HB-2: futures sizing gate
    return config


@pytest.fixture
def mock_safety_layer(mock_settings):
    """SafetyLayer instance with test config."""
    return SafetyLayer(mock_settings)


@pytest.fixture
def mock_portfolio():
    """Standard test portfolio state."""
    return {
        "total_value": 10_000.0,
        "available_cash": 50_000.0,
        "margin_used_pct": 0.0,
        "daily_pnl": 0.0,
        "open_position_count": 0,
        "positions": [],
    }


@pytest.fixture
def mock_technical_report():
    """Sample technical analyst report."""
    return TechnicalReport(
        symbol="MES",
        timestamp=datetime.now(),
        timeframe="1h",
        current_price=5800.0,
        regime=MarketRegime.TRENDING_BULL,
        trend=TrendDirection.STRONG_BULL,
        entry_signal=EntrySignal.ENTRY_NOW,
        confidence=0.85,
        notes="Strong bullish setup on 1h chart",
        key_support=[5790.0, 5780.0],
        key_resistance=[5820.0, 5840.0],
        stop_level=5785.0,
        target_1=5815.0,
        target_2=5835.0,
        target_3=5860.0,
    )


@pytest.fixture
def mock_news_report():
    """Sample news analyst report."""
    return NewsReport(
        symbol="MES",
        timestamp=datetime.now(),
        sentiment="bullish",
        sentiment_score=0.65,
        key_headlines=["Fed holds rates steady", "Tech stocks rally"],
        macro_events=["FOMC decision"],
        risk_events=[],
        confidence=0.75,
        notes="Market reacting positively to Fed clarity",
    )


@pytest.fixture
def mock_social_report():
    """Sample social analyst report."""
    return SocialReport(
        symbol="MES",
        timestamp=datetime.now(),
        options_flow="neutral",
        put_call_ratio=1.1,
        dark_pool_activity="neutral",
        sentiment_score=0.55,
        confidence=0.60,
        notes="Mixed positioning in options",
    )


@pytest.fixture
def mock_fundamental_report():
    """Sample fundamental analyst report."""
    return FundamentalReport(
        symbol="MES",
        timestamp=datetime.now(),
        earnings_date=None,
        economic_events=["Fed decision"],
        sector_strength="strong",
        macro_bias="bullish",
        confidence=0.70,
        notes="Macro environment supportive",
    )


@pytest.fixture
def mock_pipeline_result():
    """Complete pipeline execution result."""
    return {
        "symbol": "MES",
        "is_futures": True,
        "started_at": "2026-03-29T10:00:00",
        "completed_at": "2026-03-29T10:00:05",
        "analyst_reports": {
            "technical": {
                "regime": "TRENDING_BULL",
                "trend": "STRONG_BULL",
                "entry_signal": "ENTRY_NOW",
                "confidence": 0.85,
            },
            "news": {"sentiment": "bullish", "sentiment_score": 0.65, "confidence": 0.75},
            "social": {
                "options_flow": "neutral",
                "sentiment_score": 0.55,
                "confidence": 0.60,
            },
            "fundamental": {
                "sector_strength": "strong",
                "macro_bias": "bullish",
                "confidence": 0.70,
            },
        },
        "debate_result": {
            "verdict": "bull",
            "bull_score": 7.5,
            "bear_score": 2.5,
            "margin": 5.0,
        },
        "trade_decision": {
            "symbol": "MES",
            "action": "BUY",
            "quantity": 1,
            "order_type": "LIMIT",
            "entry_price": 5800.0,
            "stop_price": 5785.0,
            "target_1": 5815.0,
            "target_2": 5835.0,
            "target_3": 5860.0,
            "conviction": 0.75,
        },
        "risk_decision": {
            "symbol": "MES",
            "approved": True,
            "approved_action": "BUY",
            "approved_contracts": 1,
            "approved_stop": 5785.0,
        },
        "fund_decision": {
            "symbol": "MES",
            "execute": True,
            "action": "BUY",
            "contracts": 1,
            "entry_price": 5800.0,
            "stop_price": 5785.0,
            "target_1": 5815.0,
            "final_conviction": 0.75,
            "human_approval_required": True,
        },
        "final_action": "buy",
        "final_quantity": 1,
        "requires_human": True,
        "errors": [],
    }


@pytest.fixture
def mock_analyst_reports():
    """Dict of all analyst reports for pipeline testing."""
    return {
        "technical": {
            "signal": 0.8,
            "confidence": 0.85,
            "summary": "Bullish momentum",
            "regime": "TRENDING_BULL",
            "trend": "STRONG_BULL",
        },
        "news": {
            "signal": 0.6,
            "confidence": 0.75,
            "summary": "Positive macro sentiment",
        },
        "social": {
            "signal": 0.5,
            "confidence": 0.60,
            "summary": "Mixed positioning",
        },
        "fundamental": {
            "signal": 0.7,
            "confidence": 0.70,
            "summary": "Supportive environment",
        },
    }


# ===========================================================================
# DATABASE & TRACKING FIXTURES
# ===========================================================================
# Naming convention: mock_{system}_manager, mock_{feature}_tracker, etc.
# All fixtures here are reusable across multiple test files.
# ===========================================================================


@pytest.fixture
def mock_db_manager():
    """Mock database manager for testing."""
    from unittest.mock import MagicMock

    manager = MagicMock()
    manager.get_open_trades.return_value = []
    manager.get_closed_trades.return_value = []
    manager.insert_trade.return_value = 1
    manager.close_trade.return_value = True
    return manager


@pytest.fixture
def mock_paper_tracker():
    """Mock portfolio tracker for testing."""
    from unittest.mock import MagicMock

    tracker = MagicMock()
    tracker.get_open_positions.return_value = []
    tracker.get_performance.return_value = {
        "today_pnl": 0.0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "profit_factor": 1.0,
    }
    tracker.get_portfolio_summary.return_value = {
        "total_value": 10000.0,
        "available_cash": 10000.0,
        "margin_used": 0.0,
    }
    return tracker


@pytest.fixture
def sample_trades():
    """Sample open and closed trades for analytics testing."""
    from datetime import datetime, timedelta

    base_time = datetime(2026, 3, 29)
    return {
        "open": [
            {
                "trade_id": "t1",
                "symbol": "MES",
                "side": "buy",
                "quantity": 1.0,
                "entry_price": 5800.0,
                "entry_time": base_time.isoformat(),
                "status": "open",
            },
        ],
        "closed": [
            {
                "trade_id": "t2",
                "symbol": "MNQ",
                "side": "sell",
                "quantity": 1.0,
                "entry_price": 20000.0,
                "exit_price": 19900.0,
                "entry_time": (base_time - timedelta(hours=1)).isoformat(),
                "exit_time": base_time.isoformat(),
                "pnl": 100.0,
                "return_pct": 0.005,
                "status": "closed",
            },
        ],
    }


@pytest.fixture
def sample_closed_trades():
    """Sample closed trades for backtest and analytics."""
    from datetime import datetime, timedelta

    base_time = datetime(2026, 3, 29)
    return [
        {
            "symbol": "MCL",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "pnl": 10.0,
            "return_pct": 0.10,
            "timestamp": base_time.isoformat(),
            "side": "buy",
            "quantity": 1.0,
        },
        {
            "symbol": "MNQ",
            "entry_price": 200.0,
            "exit_price": 190.0,
            "pnl": -10.0,
            "return_pct": -0.05,
            "timestamp": (base_time + timedelta(hours=2)).isoformat(),
            "side": "buy",
            "quantity": 1.0,
        },
    ]


@pytest.fixture
def mock_analytics_result():
    """Mock analytics calculation result."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.sharpe_ratio = 2.5
    result.profit_factor = 3.0
    result.max_drawdown_pct = 0.05
    result.win_rate = 0.67
    result.expectancy = 8.33
    result.total_trades = 3
    result.total_pnl = 15.0
    result.avg_win = 10.0
    result.avg_loss = 5.0
    result.best_trade = 10.0
    result.worst_trade = -5.0
    return result


# ===========================================================================
# MARKET & BROKER FIXTURES
# ===========================================================================


@pytest.fixture
def mock_ib_gateway():
    """Mock IB Gateway manager for futures/options testing."""
    from unittest.mock import AsyncMock, Mock

    mock = AsyncMock()
    mock.is_connected = Mock(return_value=True)
    mock.connect.return_value = True
    mock.disconnect.return_value = None
    mock.get_positions.return_value = []
    mock.place_order.return_value = {"order_id": "test_order"}
    return mock


@pytest.fixture
def mock_broker_connection():
    """Mock generic broker connection."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.is_connected.return_value = True
    mock.get_account_value.return_value = 50000.0
    return mock


# ===========================================================================
# HTTP CLIENT FIXTURES
# ===========================================================================
# Use these for FastAPI endpoint testing. Each router-specific client can
# extend this by including its own router in a local fixture if needed.
# ===========================================================================


@pytest.fixture
def test_client():
    """FastAPI TestClient with mock app and API key auth."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    # Add auth headers matching conftest env vars
    client = TestClient(app, headers={"X-API-Key": _real_api_key})
    return client


# ===========================================================================
# IB GATEWAY RESILIENCE FIXTURES
# ===========================================================================


@pytest.fixture
def settings_paper(mock_settings):
    """Paper trading settings for IB connector tests."""
    mock_settings.PAPER_TRADING = True
    return mock_settings


@pytest.fixture
def settings_live(mock_settings):
    """Live trading settings for IB connector tests."""
    mock_settings.PAPER_TRADING = False
    mock_settings.LIVE_TRADING_ENABLED = False  # Still disabled for safety
    return mock_settings


@pytest.fixture
def settings(mock_settings):
    """Default settings fixture (alias for mock_settings)."""
    return mock_settings


@pytest.fixture
def safety_layer_mock():
    """Mock SafetyLayer for connector testing."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.check_order.return_value = MagicMock(approved=True, rejection_reason=None, warnings=[])
    mock.on_connection_state_change = MagicMock()
    return mock
