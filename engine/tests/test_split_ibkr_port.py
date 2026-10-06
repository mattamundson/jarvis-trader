"""
Tests for split IBKR port configuration (market data on 4001, execution on 4002).

Verifies:
- Market data connections can use 4001 when IBKR_MARKET_DATA_PORT is set
- Execution connections still reject 4001
- Default behavior unchanged when split-port settings not configured
- Startup checks pass with split-port config
- No orders can be placed through the market data connection when on a live port
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from dataclasses import dataclass

from config import TradingConfig
from startup_checks import _check_ibkr_port
from data.market_data import resolve_data_client_id


@dataclass
class MockConfig:
    """Mock config for testing."""
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4002
    IBKR_CLIENT_ID: int = 1
    IBKR_MARKET_DATA_HOST: str | None = None
    IBKR_MARKET_DATA_PORT: int | None = None
    IBKR_MARKET_DATA_CLIENT_ID: int | None = None
    POLYGON_API_KEY: str | None = None
    FINNHUB_API_KEY: str | None = None


class TestSplitIBKRPort:
    """Test split IBKR port configuration."""

    def test_default_config_unchanged(self):
        """Default config should use same port for execution and data."""
        config = MockConfig()
        assert config.IBKR_PORT == 4002
        assert config.IBKR_MARKET_DATA_PORT is None
        
        # Startup check should pass for default paper config
        result = _check_ibkr_port(config)
        assert result.status == "pass"
        assert "4002" in result.message

    def test_execution_port_4001_rejected(self):
        """Execution port 4001 should fail startup check."""
        config = MockConfig(IBKR_PORT=4001)
        result = _check_ibkr_port(config)
        assert result.status == "fail"
        assert "live trading" in result.message.lower()

    def test_market_data_port_4001_allowed(self):
        """Market data on 4001 with execution on 4002 should pass."""
        config = MockConfig(
            IBKR_PORT=4002,  # Execution stays paper
            IBKR_MARKET_DATA_PORT=4001  # Market data uses live
        )
        result = _check_ibkr_port(config)
        assert result.status == "pass"
        assert "4002" in result.message
        assert "4001" in result.message
        assert "read-only" in result.message.lower()

    def test_client_id_isolation_default(self):
        """Market data should use CLIENT_ID + 1 by default (backward compatible)."""
        config = MockConfig(IBKR_CLIENT_ID=2)
        data_id = resolve_data_client_id(config)
        assert data_id == 3  # 2 + 1 (not +100, for backward compatibility)

    def test_client_id_explicit_market_data(self):
        """Explicit market data client ID should be used when set."""
        config = MockConfig(IBKR_CLIENT_ID=238)
        config.IBKR_MARKET_DATA_CLIENT_ID = 338
        data_id = resolve_data_client_id(config)
        assert data_id == 338

    def test_execution_path_rejects_live_port(self):
        """Execution path (IBGatewayConfig) should reject port 4001."""
        from execution.ib_gateway import IBGatewayConfig
        
        # Should raise ValueError for port 4001
        with pytest.raises(ValueError, match="SAFETY VIOLATION.*4001"):
            IBGatewayConfig(port=4001)
        
        # Should also reject port 7496 (TWS live)
        with pytest.raises(ValueError, match="SAFETY VIOLATION.*7496"):
            IBGatewayConfig(port=7496)
        
        # Should accept port 4002
        cfg = IBGatewayConfig(port=4002)
        assert cfg.port == 4002

    @pytest.mark.asyncio
    async def test_market_data_uses_split_port(self):
        """MarketDataManager should use split port when configured."""
        from data.market_data import MarketDataManager, IBKRDataConnector
        
        config = MockConfig(
            IBKR_PORT=4002,
            IBKR_MARKET_DATA_PORT=4001,
            IBKR_MARKET_DATA_CLIENT_ID=338
        )
        
        manager = MarketDataManager(config)
        
        # Mock the IBKRDataConnector to track its construction
        with patch('data.market_data.IBKRDataConnector') as mock_connector_class:
            mock_connector = Mock()
            mock_connector.connect = AsyncMock(return_value=True)
            mock_connector_class.return_value = mock_connector
            
            await manager.initialize()
            
            # Verify IBKRDataConnector was created with correct params
            mock_connector_class.assert_called_once()
            call_kwargs = mock_connector_class.call_args[1]
            assert call_kwargs['port'] == 4001
            assert call_kwargs['readonly'] is True
            assert call_kwargs['client_id'] == 338

    @pytest.mark.asyncio
    async def test_market_data_uses_tws_live_port(self):
        """MarketDataManager should force readonly for TWS live port 7496."""
        from data.market_data import MarketDataManager, IBKRDataConnector
        
        config = MockConfig(
            IBKR_PORT=4002,
            IBKR_MARKET_DATA_PORT=7496,  # TWS live
            IBKR_MARKET_DATA_CLIENT_ID=338
        )
        
        manager = MarketDataManager(config)
        
        with patch('data.market_data.IBKRDataConnector') as mock_connector_class:
            mock_connector = Mock()
            mock_connector.connect = AsyncMock(return_value=True)
            mock_connector_class.return_value = mock_connector
            
            await manager.initialize()
            
            # Verify readonly=True for TWS live port
            call_kwargs = mock_connector_class.call_args[1]
            assert call_kwargs['port'] == 7496
            assert call_kwargs['readonly'] is True

    def test_health_reports_both_ports(self):
        """Health endpoint should report both execution and data ports when split."""
        from routers.health_router import _check_ibgateway_alive, _check_ibgateway_data_port_alive
        
        # Execution port check (always runs)
        exec_alive, exec_port = _check_ibgateway_alive()
        assert isinstance(exec_alive, bool)
        assert isinstance(exec_port, int)
        
        # Data port check (returns None when not configured)
        data_alive, data_port = _check_ibgateway_data_port_alive()
        assert isinstance(data_alive, bool)
        # data_port can be None or int depending on config


class TestIBKRDataConnectorReadonly:
    """Test readonly parameter on IBKRDataConnector."""

    @pytest.mark.asyncio
    async def test_readonly_passed_to_ib_async(self):
        """Connector should pass readonly parameter to ib_async connectAsync."""
        from data.market_data import IBKRDataConnector
        
        with patch('ib_async.IB') as mock_ib_class:
            mock_ib = Mock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.disconnectedEvent = Mock()
            mock_ib.reqMarketDataType = Mock()
            mock_ib_class.return_value = mock_ib
            
            connector = IBKRDataConnector(
                host="127.0.0.1",
                port=4001,
                client_id=338,
                readonly=True
            )
            
            await connector.connect()
            
            # Verify connectAsync was called with readonly=True
            mock_ib.connectAsync.assert_called_once()
            call_kwargs = mock_ib.connectAsync.call_args[1]
            assert call_kwargs['readonly'] is True
            assert call_kwargs['clientId'] == 338

    @pytest.mark.asyncio
    async def test_no_order_methods_on_data_connector(self):
        """IBKRDataConnector should not expose order placement methods."""
        from data.market_data import IBKRDataConnector
        
        connector = IBKRDataConnector(
            host="127.0.0.1",
            port=4001,
            readonly=True
        )
        
        # Verify connector doesn't have order placement methods
        assert not hasattr(connector, 'place_order')
        assert not hasattr(connector, 'placeOrder')
        assert not hasattr(connector, 'submit_order')
        assert not hasattr(connector, 'cancel_order')
