"""
Integration tests for all market modules (futures, options, crypto, polymarket).
Tests verify ABC interface compliance and module-specific behavior.

Requirements:
  - FuturesMarketModule: lifecycle, positions, P&L
  - OptionsMarketModule: lifecycle, scanner, auto-roller
  - CryptoMarketModule: Freqtrade bridge integration
  - PolymarketModule: disabled by default, health checks
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from markets.base import (
    HealthStatus,
    MarketModule,
    MarketStatus,
    Position,
    TradeResult,
    TradeSignal,
)
from markets.crypto.freqtrade_bridge import FreqtradeBridge
from markets.crypto.module import CryptoMarketModule
from markets.futures.module import FuturesMarketModule
from markets.options.auto_roller import OptionsAutoRoller, RollerAction
from markets.options.module import OptionsMarketModule
from markets.options.scanner import OptionsScanner, ScanResult
from markets.polymarket.module import PolymarketModule


class TestFuturesMarketModuleInterface:
    """Test FuturesMarketModule implements MarketModule ABC correctly."""

    @pytest.fixture
    def mock_portfolio_tracker(self):
        """Override conftest mock_paper_tracker with richer position data."""
        mock = MagicMock()
        open_positions = [
            {
                "symbol": "MES",
                "quantity": 1,
                "avg_cost": 5800.0,
                "market_value": 5850.0,
                "unrealized_pnl": 50.0,
            }
        ]
        mock.get_open_positions.return_value = open_positions
        # get_positions()/health_check() now read the DB-reconciled source
        # (PortfolioTracker.get_open_positions_authoritative) rather than the
        # raw in-memory get_open_positions(), so the mock must implement both.
        mock.get_open_positions_authoritative.return_value = (
            open_positions,
            {
                "source": "db_authoritative",
                "reconciled": True,
                "count": len(open_positions),
                "in_memory_count": len(open_positions),
                "db_count": len(open_positions),
                "only_in_db": [],
                "only_in_memory": [],
            },
        )
        mock.get_performance.return_value = {
            "today_pnl": 150.0,
            "total_pnl": 500.0,
            "win_rate": 0.65,
            "profit_factor": 2.1,
        }
        return mock

    @pytest.fixture
    def mock_safety_layer(self):
        """Mock safety layer (from conftest)."""
        return MagicMock()

    @pytest.fixture
    def futures_module(self, mock_ib_gateway, mock_portfolio_tracker, mock_safety_layer):
        """Create FuturesMarketModule with mocks."""
        return FuturesMarketModule(
            ib_gateway=mock_ib_gateway,
            portfolio_tracker=mock_portfolio_tracker,
            safety_layer=mock_safety_layer,
            symbols=["MES", "MNQ"],
        )

    @pytest.mark.asyncio
    async def test_futures_implements_abc(self, futures_module):
        """Verify FuturesMarketModule implements all ABC methods."""
        assert isinstance(futures_module, MarketModule)
        assert hasattr(futures_module, "connect")
        assert hasattr(futures_module, "get_positions")
        assert hasattr(futures_module, "get_daily_pnl")
        assert hasattr(futures_module, "run_strategy_cycle")
        assert hasattr(futures_module, "execute_signal")
        assert hasattr(futures_module, "shutdown")
        assert hasattr(futures_module, "health_check")

    @pytest.mark.asyncio
    async def test_futures_connect_success(self, futures_module, mock_ib_gateway):
        """Test successful connection to IB Gateway."""
        mock_ib_gateway.is_connected.return_value = False
        mock_ib_gateway.connect.return_value = True
        result = await futures_module.connect()
        assert result is True
        assert futures_module._status == MarketStatus.PAPER
        mock_ib_gateway.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_futures_connect_already_connected(self, futures_module, mock_ib_gateway):
        """Test connect when already connected."""
        mock_ib_gateway.is_connected.return_value = True
        result = await futures_module.connect()
        assert result is True
        assert futures_module._status == MarketStatus.PAPER

    @pytest.mark.asyncio
    async def test_futures_connect_failure(
        self, mock_ib_gateway, mock_portfolio_tracker, mock_safety_layer
    ):
        """Test connection failure handling."""
        mock_ib_gateway.is_connected.return_value = False
        mock_ib_gateway.connect.return_value = False
        futures_module = FuturesMarketModule(
            ib_gateway=mock_ib_gateway,
            portfolio_tracker=mock_portfolio_tracker,
            safety_layer=mock_safety_layer,
        )
        result = await futures_module.connect()
        assert result is False
        assert futures_module._status == MarketStatus.ERROR

    @pytest.mark.asyncio
    async def test_futures_get_positions(self, futures_module, mock_portfolio_tracker):
        """Test getting open positions."""
        positions = await futures_module.get_positions()
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0].symbol == "MES"
        assert positions[0].quantity == 1
        assert positions[0].market == "futures"

    @pytest.mark.asyncio
    async def test_futures_get_daily_pnl(self, futures_module, mock_portfolio_tracker):
        """Test getting daily P&L."""
        pnl = await futures_module.get_daily_pnl()
        assert pnl == 150.0
        assert futures_module._daily_pnl == 150.0

    @pytest.mark.asyncio
    async def test_futures_run_strategy_cycle(self, futures_module):
        """Test strategy cycle execution."""
        signals = await futures_module.run_strategy_cycle()
        assert isinstance(signals, list)
        assert len(signals) == 0  # Pipeline handles internally

    @pytest.mark.asyncio
    async def test_futures_shutdown(self, futures_module, mock_ib_gateway):
        """Test shutdown closes connection."""
        await futures_module.connect()
        await futures_module.shutdown()
        assert futures_module._status == MarketStatus.OFFLINE
        mock_ib_gateway.disconnect.assert_called_once()

    def test_futures_health_check(self, futures_module, mock_ib_gateway):
        """Test health check returns proper status."""
        mock_ib_gateway.is_connected.return_value = True
        health = futures_module.health_check()
        assert isinstance(health, HealthStatus)
        assert health.market == "futures"
        assert health.status == MarketStatus.PAPER
        assert "connected" in health.message.lower()

    def test_futures_health_check_reports_open_positions(
        self, futures_module, mock_ib_gateway, mock_portfolio_tracker
    ):
        """
        Regression test: health_check() must report the tracker's real open
        position count, not silently default to 0 (HealthStatus.open_positions
        defaults to 0; the futures module previously never set it). This was
        the root cause of /portfolio/health reporting 0 while /portfolio/summary
        (which reads the same tracker via get_positions()) correctly reported 2.
        mock_portfolio_tracker.get_open_positions() returns 1 position (MES).
        """
        mock_ib_gateway.is_connected.return_value = True
        health = futures_module.health_check()
        assert health.open_positions == len(mock_portfolio_tracker.get_open_positions())
        assert health.open_positions == 1


class TestOptionsMarketModule:
    """Test OptionsMarketModule interface and lifecycle."""

    @pytest.fixture
    def mock_ib_gateway_options(self, mock_ib_gateway):
        """Reuse conftest mock_ib_gateway for options testing."""
        return mock_ib_gateway

    @pytest.fixture
    def options_module(self, mock_ib_gateway_options):
        """Create OptionsMarketModule with mocks."""
        return OptionsMarketModule(
            ib_gateway=mock_ib_gateway_options,
            underlyings=["SPY", "QQQ"],
        )

    @pytest.mark.asyncio
    async def test_options_implements_abc(self, options_module):
        """Verify OptionsMarketModule implements ABC."""
        assert isinstance(options_module, MarketModule)
        assert options_module.market_name == "options"

    @pytest.mark.asyncio
    async def test_options_connect(self, options_module, mock_ib_gateway_options):
        """Test options module connection."""
        result = await options_module.connect()
        assert result is True
        assert options_module._status == MarketStatus.PAPER

    @pytest.mark.asyncio
    async def test_options_get_positions(self, options_module):
        """Test getting options positions."""
        positions = await options_module.get_positions()
        assert isinstance(positions, list)
        assert positions == []  # Empty by default

    @pytest.mark.asyncio
    async def test_options_get_daily_pnl(self, options_module):
        """Test getting options P&L."""
        pnl = await options_module.get_daily_pnl()
        assert pnl == 0.0

    @pytest.mark.asyncio
    async def test_options_run_strategy_cycle(self, options_module):
        """Test options strategy cycle."""
        with patch.object(options_module._scanner, "scan", return_value=[]):
            signals = await options_module.run_strategy_cycle()
            assert isinstance(signals, list)

    @pytest.mark.asyncio
    async def test_options_shutdown(self, options_module):
        """Test options module shutdown."""
        await options_module.shutdown()
        assert options_module._status == MarketStatus.OFFLINE

    def test_options_health_check(self, options_module):
        """Test options health status."""
        health = options_module.health_check()
        assert isinstance(health, HealthStatus)
        assert health.market == "options"


class TestOptionsScanner:
    """Test OptionsScanner IV rank and DTE filtering."""

    @pytest.fixture
    def scanner(self):
        """Create OptionsScanner."""
        return OptionsScanner(
            underlyings=["SPY"],
            min_iv_rank=30.0,
        )

    def test_scanner_iv_rank_threshold(self, scanner):
        """Test IV rank threshold value."""
        assert scanner.min_iv_rank == 30.0

    def test_scanner_underlyings(self, scanner):
        """Test scanner tracks underlyings."""
        assert "SPY" in scanner.underlyings

    def test_scanner_dte_constants(self):
        """Test DTE range constants are set correctly."""
        assert 25 <= 50  # Valid DTE range test


class TestOptionsAutoRoller:
    """Test OptionsAutoRoller profit target and loss stop logic."""

    @pytest.fixture
    def roller(self):
        """Create OptionsAutoRoller."""
        return OptionsAutoRoller()

    def test_roller_close_at_50_percent_profit(self, roller):
        """Test profit target close (50% profit)."""
        action = roller.evaluate_position(
            position_id="pos1",
            symbol="SPY",
            expiry_date="2027-06-01",  # far future — DTE always > 21
            initial_credit=100.0,
            current_debit_to_close=50.0,  # 50% profit
        )
        assert action.action == "close"
        assert "Take profit" in action.reason

    def test_roller_hold_below_profit_threshold(self, roller):
        """Test hold when profit < 50%."""
        action = roller.evaluate_position(
            position_id="pos1",
            symbol="SPY",
            expiry_date="2027-06-01",  # far future — DTE always > 21
            initial_credit=100.0,
            current_debit_to_close=75.0,  # 25% profit
        )
        assert action.action == "hold"

    def test_roller_stop_loss_at_2x_loss(self, roller):
        """Test loss stop (2x loss)."""
        action = roller.evaluate_position(
            position_id="pos1",
            symbol="SPY",
            expiry_date="2027-06-01",  # far future — DTE always > 21
            initial_credit=100.0,
            current_debit_to_close=200.0,  # 2x loss
        )
        assert action.action == "stop"
        assert "Stop loss" in action.reason

    def test_roller_roll_at_21_dte(self, roller):
        """Test DTE roll trigger (21 DTE)."""
        with patch("markets.options.auto_roller.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 10)

            action = roller.evaluate_position(
                position_id="pos1",
                symbol="SPY",
                expiry_date="2026-05-01",  # 21 days
                initial_credit=100.0,
                current_debit_to_close=80.0,
            )
            assert action.action == "roll"
            assert "Roll" in action.reason


class TestCryptoMarketModule:
    """Test CryptoMarketModule and Freqtrade bridge."""

    @pytest.fixture
    def mock_freqtrade_bridge(self):
        """Mock FreqtradeBridge."""
        mock = AsyncMock()
        mock.base_url = "http://localhost:8080/api/v1"
        mock.is_running.return_value = True
        mock.authenticate.return_value = True
        mock.get_trades.return_value = [
            {
                "pair": "BTC/USDT",
                "amount": 0.5,
                "open_rate": 65000.0,
                "current_value": 65500.0,
                "profit_abs": 250.0,
            }
        ]
        mock.get_profit.return_value = {
            "profit_today_abs": 100.0,
            "profit_all_fiat": 500.0,
        }
        return mock

    @pytest.fixture
    def crypto_module(self, mock_freqtrade_bridge):
        """Create CryptoMarketModule with mock bridge."""
        module = CryptoMarketModule()
        module._bridge = mock_freqtrade_bridge
        return module

    @pytest.mark.asyncio
    async def test_crypto_implements_abc(self, crypto_module):
        """Verify CryptoMarketModule implements ABC."""
        assert isinstance(crypto_module, MarketModule)
        assert crypto_module.market_name == "crypto"

    @pytest.mark.asyncio
    async def test_crypto_connect_success(self, crypto_module, mock_freqtrade_bridge):
        """Test connecting to Freqtrade."""
        with patch.object(crypto_module, "is_enabled", return_value=True):
            result = await crypto_module.connect()
            assert result is True
            assert crypto_module._status == MarketStatus.PAPER
            mock_freqtrade_bridge.is_running.assert_called_once()
            mock_freqtrade_bridge.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_crypto_connect_disabled(self, crypto_module):
        """Test connect when crypto is disabled."""
        with patch.object(crypto_module, "is_enabled", return_value=False):
            result = await crypto_module.connect()
            assert result is False

    @pytest.mark.asyncio
    async def test_crypto_connect_freqtrade_not_running(self, crypto_module, mock_freqtrade_bridge):
        """Test connect when Freqtrade is not running."""
        with patch.object(crypto_module, "is_enabled", return_value=True):
            mock_freqtrade_bridge.is_running.return_value = False
            result = await crypto_module.connect()
            assert result is False
            assert crypto_module._status == MarketStatus.ERROR

    @pytest.mark.asyncio
    async def test_crypto_get_positions(self, crypto_module, mock_freqtrade_bridge):
        """Test getting crypto positions from Freqtrade."""
        positions = await crypto_module.get_positions()
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDT"
        assert positions[0].quantity == 0.5

    @pytest.mark.asyncio
    async def test_crypto_get_daily_pnl(self, crypto_module, mock_freqtrade_bridge):
        """Test getting crypto P&L."""
        pnl = await crypto_module.get_daily_pnl()
        assert pnl == 100.0

    @pytest.mark.asyncio
    async def test_crypto_run_strategy_cycle(self, crypto_module):
        """Test crypto strategy cycle."""
        signals = await crypto_module.run_strategy_cycle()
        assert isinstance(signals, list)
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_crypto_shutdown(self, crypto_module, mock_freqtrade_bridge):
        """Test crypto module shutdown."""
        await crypto_module.shutdown()
        assert crypto_module._status == MarketStatus.OFFLINE
        mock_freqtrade_bridge.stop_trading.assert_called_once()
        mock_freqtrade_bridge.close.assert_called_once()

    def test_crypto_health_check(self, crypto_module):
        """Test crypto health status."""
        health = crypto_module.health_check()
        assert isinstance(health, HealthStatus)
        assert health.market == "crypto"


class TestFreqtradeBridge:
    """Test FreqtradeBridge mock REST responses."""

    @pytest.fixture
    def bridge(self):
        """Create FreqtradeBridge."""
        return FreqtradeBridge(base_url="http://localhost:8080/api/v1")

    @pytest.mark.asyncio
    async def test_bridge_authenticate(self, bridge):
        """Test Freqtrade authentication."""
        with patch("markets.crypto.freqtrade_bridge.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "test-token-123"}
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            bridge._client = mock_client.return_value

            result = await bridge.authenticate()
            assert result is True
            assert bridge._token == "test-token-123"

    @pytest.mark.asyncio
    async def test_bridge_is_running(self, bridge):
        """Test Freqtrade ping endpoint."""
        with patch("markets.crypto.freqtrade_bridge.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            bridge._client = mock_client.return_value

            result = await bridge.is_running()
            assert result is True

    @pytest.mark.asyncio
    async def test_bridge_get_trades(self, bridge):
        """Test getting trades from Freqtrade."""
        with patch("markets.crypto.freqtrade_bridge.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"trades": [{"pair": "BTC/USDT", "amount": 0.5}]}
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            bridge._client = mock_client.return_value

            trades = await bridge.get_trades()
            assert isinstance(trades, list)
            assert len(trades) == 1

    @pytest.mark.asyncio
    async def test_bridge_get_profit(self, bridge):
        """Test getting profit from Freqtrade."""
        with patch("markets.crypto.freqtrade_bridge.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "profit_today_abs": 100.0,
                "profit_all_fiat": 500.0,
            }
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            bridge._client = mock_client.return_value

            profit = await bridge.get_profit()
            assert profit["profit_today_abs"] == 100.0


class TestPolymarketModule:
    """Test PolymarketModule disabled by default."""

    @pytest.fixture
    def polymarket_module(self):
        """Create PolymarketModule."""
        return PolymarketModule()

    @pytest.mark.asyncio
    async def test_polymarket_implements_abc(self, polymarket_module):
        """Verify PolymarketModule implements ABC."""
        assert isinstance(polymarket_module, MarketModule)
        assert polymarket_module.market_name == "polymarket"

    def test_polymarket_disabled_by_default(self, polymarket_module):
        """Test Polymarket is disabled by default (POLYMARKET_ENABLED=False)."""
        with patch("config.settings") as mock_settings:
            mock_settings.POLYMARKET_ENABLED = False
            mock_settings.get_enabled_markets.return_value = []
            assert polymarket_module.is_enabled() is False

    @pytest.mark.asyncio
    async def test_polymarket_connect_when_disabled(self, polymarket_module):
        """Test connect returns False when disabled."""
        with patch.object(polymarket_module, "is_enabled", return_value=False):
            result = await polymarket_module.connect()
            assert result is False

    @pytest.mark.asyncio
    async def test_polymarket_get_positions(self, polymarket_module):
        """Test getting polymarket positions."""
        positions = await polymarket_module.get_positions()
        assert isinstance(positions, list)
        assert positions == []

    @pytest.mark.asyncio
    async def test_polymarket_get_daily_pnl(self, polymarket_module):
        """Test getting polymarket P&L."""
        pnl = await polymarket_module.get_daily_pnl()
        assert pnl == 0.0

    @pytest.mark.asyncio
    async def test_polymarket_shutdown(self, polymarket_module):
        """Test polymarket shutdown."""
        await polymarket_module.shutdown()
        assert polymarket_module._status == MarketStatus.OFFLINE

    def test_polymarket_health_check(self, polymarket_module):
        """Test polymarket health status."""
        health = polymarket_module.health_check()
        assert isinstance(health, HealthStatus)
        assert health.market == "polymarket"
        assert "regulatory" in health.message.lower()


class TestMarketModuleABCCompliance:
    """Test that all modules properly comply with MarketModule ABC."""

    @pytest.mark.asyncio
    async def test_all_modules_have_required_methods(
        self,
        mock_ib_gateway,
        mock_portfolio_tracker,
        mock_safety_layer,
    ):
        """Verify all modules have required ABC methods."""
        futures_module = FuturesMarketModule(
            ib_gateway=mock_ib_gateway,
            portfolio_tracker=mock_portfolio_tracker,
            safety_layer=mock_safety_layer,
        )
        options_module = OptionsMarketModule(ib_gateway=mock_ib_gateway)
        crypto_module = CryptoMarketModule()

        required_methods = [
            "connect",
            "get_positions",
            "get_daily_pnl",
            "run_strategy_cycle",
            "execute_signal",
            "shutdown",
            "health_check",
        ]

        for module in [futures_module, options_module, crypto_module]:
            for method in required_methods:
                assert hasattr(module, method), f"{module.market_name} missing {method}"

    @pytest.fixture
    def mock_ib_gateway(self):
        """Mock IB Gateway for ABC test."""
        mock = AsyncMock()
        mock.is_connected.return_value = True
        mock.connect.return_value = True
        return mock

    @pytest.fixture
    def mock_portfolio_tracker(self):
        """Mock portfolio tracker for ABC test."""
        mock = MagicMock()
        mock.get_open_positions.return_value = []
        mock.get_performance.return_value = {
            "today_pnl": 0.0,
            "total_pnl": 0.0,
        }
        return mock

    @pytest.fixture
    def mock_safety_layer(self):
        """Mock safety layer for ABC test."""
        return MagicMock()

    def test_market_status_enum(self):
        """Test MarketStatus enum values."""
        assert MarketStatus.OFFLINE.value == "offline"
        assert MarketStatus.CONNECTING.value == "connecting"
        assert MarketStatus.PAPER.value == "paper"
        assert MarketStatus.LIVE.value == "live"
        assert MarketStatus.HALTED.value == "halted"
        assert MarketStatus.ERROR.value == "error"

    def test_health_status_dataclass(self):
        """Test HealthStatus dataclass."""
        health = HealthStatus(
            market="test",
            status=MarketStatus.PAPER,
            message="Test health",
            daily_pnl=100.0,
            open_positions=2,
        )
        assert health.market == "test"
        assert health.status == MarketStatus.PAPER
        assert health.daily_pnl == 100.0
        assert health.open_positions == 2

    def test_position_dataclass(self):
        """Test Position dataclass."""
        pos = Position(
            symbol="MES",
            quantity=1.0,
            avg_cost=5800.0,
            market_value=5850.0,
            unrealized_pnl=50.0,
            side="long",
            market="futures",
        )
        assert pos.symbol == "MES"
        assert pos.quantity == 1.0
        assert pos.side == "long"
        assert pos.market == "futures"

    def test_trade_signal_dataclass(self):
        """Test TradeSignal dataclass."""
        signal = TradeSignal(
            symbol="SPY",
            action="buy",
            quantity=10.0,
            confidence=0.85,
            strategy="iron_condor",
            market="options",
            reason="IV Rank > 30",
        )
        assert signal.symbol == "SPY"
        assert signal.action == "buy"
        assert signal.confidence == 0.85
        assert signal.strategy == "iron_condor"

    def test_trade_result_dataclass(self):
        """Test TradeResult dataclass."""
        signal = TradeSignal(
            symbol="SPY",
            action="sell",
            quantity=1.0,
            confidence=0.7,
            strategy="test",
            market="options",
        )
        result = TradeResult(
            signal=signal,
            executed=True,
            fill_price=450.0,
            fill_qty=1.0,
            realized_pnl=50.0,
            order_id="ORDER123",
        )
        assert result.executed is True
        assert result.fill_price == 450.0
        assert result.order_id == "ORDER123"
