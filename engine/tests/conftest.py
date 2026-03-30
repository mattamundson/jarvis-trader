"""
JARVIS TRADER — Pytest Fixtures
Shared test fixtures for all test modules.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
import os
import sys
from pathlib import Path

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
}

for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

from config import TradingConfig
from risk.safety_layer import SafetyLayer
from agents.schemas import (
    TechnicalReport,
    NewsReport,
    SocialReport,
    FundamentalReport,
    TradeDecision,
    Action,
    OrderType,
    MarketRegime,
    TrendDirection,
    EntrySignal,
)


@pytest.fixture
def mock_settings():
    """Safe test configuration with conservative limits."""
    config = TradingConfig()
    # Override with test-safe defaults
    config.LIVE_TRADING_ENABLED = False
    config.REQUIRE_HUMAN_APPROVAL = True
    config.MAX_DAILY_LOSS_PCT = 0.02  # -2%
    config.MAX_DRAWDOWN_PCT = 0.10  # -10%
    config.MAX_POSITION_SIZE_PCT = 0.05  # 5% per position
    config.MAX_SINGLE_ORDER_VALUE = 5000.0
    config.MAX_ORDERS_PER_MINUTE = 10
    config.MAX_CONTRACTS_PER_INSTRUMENT = 2
    config.MAX_MARGIN_UTILIZATION = 0.40
    config.PRICE_COLLAR_PCT = 0.05
    config.MAX_CORRELATED_EXPOSURE_PCT = 0.20
    return config


@pytest.fixture
def mock_safety_layer(mock_settings):
    """SafetyLayer instance with test config."""
    return SafetyLayer(mock_settings)


@pytest.fixture
def mock_portfolio():
    """Standard test portfolio state."""
    return {
        "total_value": 100_000.0,
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


@pytest.fixture
def mock_debate_result():
    """Sample debate orchestrator result."""
    return {
        "verdict": "bull",
        "bull_score": 7.5,
        "bear_score": 2.5,
        "margin": 5.0,
        "consensus_direction": "STRONG_BULL",
        "recommended_action": "BUY",
        "conviction": 0.75,
        "rationale": "All layers align on bullish setup",
        "bull_arguments": ["Momentum turning positive", "Technical alignment"],
        "bear_arguments": ["Minor pullback risk"],
    }
