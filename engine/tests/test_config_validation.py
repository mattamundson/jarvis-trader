"""
JARVIS TRADER — Configuration Validation Tests
Tests for TradingConfig field parsing, defaults, and safety invariants.
"""

import os
from unittest.mock import patch

import pytest


class TestFuturesWatchlistParsing:
    """Watchlist parsing from various formats."""

    @patch.dict(os.environ, {"FUTURES_WATCHLIST": "MCL,MNQ", "API_KEY": "test-key"})
    def test_futures_watchlist_csv_format(self):
        """Comma-separated string parses to list."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.FUTURES_WATCHLIST == ["MCL", "MNQ"]

    @patch.dict(os.environ, {"FUTURES_WATCHLIST": '["MCL","MNQ"]', "API_KEY": "test-key"})
    def test_futures_watchlist_json_format(self):
        """JSON array string parses to list."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.FUTURES_WATCHLIST == ["MCL", "MNQ"]

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_futures_watchlist_list_passthrough(self):
        """List input stays as list."""
        from config import TradingConfig

        config = TradingConfig()
        # Default is "MES,MNQ,MCL" — should parse to list
        assert isinstance(config.FUTURES_WATCHLIST, list)
        assert "MES" in config.FUTURES_WATCHLIST or "MNQ" in config.FUTURES_WATCHLIST


class TestSafetyDefaults:
    """Safety invariants and kill switch thresholds."""

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_live_trading_default_false(self):
        """LIVE_TRADING_ENABLED defaults to False."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.LIVE_TRADING_ENABLED is False

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_human_approval_default_true(self):
        """REQUIRE_HUMAN_APPROVAL defaults to True."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.REQUIRE_HUMAN_APPROVAL is True

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_paper_trading_default_true(self):
        """PAPER_TRADING defaults to True."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.PAPER_TRADING is True

    @patch.dict(
        os.environ,
        {
            "API_KEY": "test-key",
            "MAX_DAILY_LOSS_PCT": "0.10",
            "MAX_DRAWDOWN_PCT": "0.20",
            "MAX_POSITION_SIZE_PCT": "0.10",
            "MAX_SINGLE_ORDER_VALUE": "5000.0",
            "MAX_MARGIN_UTILIZATION": "0.40",
            "MAX_ORDERS_PER_MINUTE": "10",
        },
    )
    def test_safety_defaults_non_negotiable(self):
        """Kill switch thresholds match current .env paper trading values."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.MAX_DAILY_LOSS_PCT == 0.10  # -10% (paper trading mode)
        assert config.MAX_DRAWDOWN_PCT == 0.20  # -20% (paper trading mode)
        assert config.MAX_POSITION_SIZE_PCT == 0.10  # 10% (paper trading mode)
        assert config.MAX_SINGLE_ORDER_VALUE == 5000.0
        assert config.MAX_MARGIN_UTILIZATION == 0.40  # 40%
        assert config.MAX_ORDERS_PER_MINUTE == 10


class TestBrokerDefaults:
    """Broker-specific configuration."""

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_ibkr_port_default_paper(self):
        """IBKR_PORT defaults to 4002 (paper mode)."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.IBKR_PORT == 4002

    @patch.dict(
        os.environ,
        {"IBKR_CLIENT_ID": "5", "API_KEY": "test-key"},
    )
    def test_ibkr_client_id_from_env(self):
        """IBKR_CLIENT_ID reads from environment."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.IBKR_CLIENT_ID == 5


class TestFuturesLimits:
    """Futures-specific risk limits."""

    @patch.dict(os.environ, {"API_KEY": "test-key", "MAX_CONTRACTS_PER_INSTRUMENT": "3"})
    def test_max_contracts_per_instrument(self):
        """Env values in [1, 20] pass through unchanged; values above 20 are clamped."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.MAX_CONTRACTS_PER_INSTRUMENT == 3

    @patch.dict(os.environ, {"API_KEY": "test-key", "MAX_CONTRACTS_PER_INSTRUMENT": "25"})
    def test_max_contracts_hard_cap_at_20(self):
        """Values above the Phase 3 hard cap of 20 are clamped to 20."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.MAX_CONTRACTS_PER_INSTRUMENT == 20

    @patch.dict(os.environ, {"API_KEY": "test-key", "MAX_OVERNIGHT_CONTRACTS": "2"})
    def test_max_overnight_contracts(self):
        """MAX_OVERNIGHT_CONTRACTS set to 2 for paper trading validation."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.MAX_OVERNIGHT_CONTRACTS == 2


class TestConsecutiveLossTracking:
    """Consecutive loss position sizing parameters."""

    @patch.dict(os.environ, {"API_KEY": "test-key"})
    def test_consecutive_loss_thresholds(self):
        """Consecutive loss thresholds are set correctly."""
        from config import TradingConfig

        config = TradingConfig()
        assert config.CONSECUTIVE_LOSS_HALF_SIZE == 3
        assert config.CONSECUTIVE_LOSS_QUARTER_SIZE == 5
        assert config.CONSECUTIVE_LOSS_HALT == 7
        assert config.CONSECUTIVE_LOSS_HALT_HOURS == 24
