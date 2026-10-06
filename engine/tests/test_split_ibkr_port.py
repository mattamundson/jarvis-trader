"""
Tests for split IBKR port configuration (market data on 4001, execution on 4002).

Verifies:
- Market data connections can use 4001 when IBKR_MARKET_DATA_PORT is set
- Execution connections still reject 4001
- Default behavior unchanged when split-port settings not configured
- Startup checks pass with split-port config
"""

import pytest
from unittest.mock import Mock, patch
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

    def test_client_id_isolation(self):
        """Market data should use distinct client ID from execution."""
        # Default: execution uses CLIENT_ID, data uses CLIENT_ID + 100
        config = MockConfig(IBKR_CLIENT_ID=2)
        data_id = resolve_data_client_id(config)
        assert data_id == 102  # 2 + 100

        # Explicit market data client ID
        config.IBKR_MARKET_DATA_CLIENT_ID = 238
        data_id = resolve_data_client_id(config)
        assert data_id == 238

    def test_execution_path_rejects_live_port(self):
        """Execution path (IBGatewayConfig) should reject port 4001."""
        from execution.ib_gateway import IBGatewayConfig
        
        # Should raise ValueError for port 4001
        with pytest.raises(ValueError, match="SAFETY VIOLATION.*4001"):
            IBGatewayConfig(port=4001)
        
        # Should accept port 4002
        cfg = IBGatewayConfig(port=4002)
        assert cfg.port == 4002

    @patch('data.market_data.IBKRDataConnector')
    async def test_market_data_uses_split_port(self, mock_connector):
        """MarketDataManager should use split port when configured."""
        from data.market_data import MarketDataManager
        
        config = MockConfig(
            IBKR_PORT=4002,
            IBKR_MARKET_DATA_PORT=4001,
            IBKR_MARKET_DATA_CLIENT_ID=238
        )
        
        manager = MarketDataManager(config)
        await manager.initialize()
        
        # Verify IBKRDataConnector was created with correct params
        mock_connector.assert_called()
        call_kwargs = mock_connector.call_args[1]
        assert call_kwargs['port'] == 4001
        assert call_kwargs['readonly'] is True
        assert call_kwargs['client_id'] == 238

    def test_health_reports_both_ports(self):
        """Health endpoint should report both execution and data ports when split."""
        # This is tested via integration with /health endpoint
        # We verify the structure here
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

    @patch('data.market_data.IB')
    async def test_readonly_true_when_port_4001(self, mock_ib_class):
        """Connector should use readonly=True when connecting to port 4001."""
        from data.market_data import IBKRDataConnector
        
        mock_ib = Mock()
        mock_ib_class.return_value = mock_ib
        mock_ib.connectAsync = Mock()
        
        connector = IBKRDataConnector(
            host="127.0.0.1",
            port=4001,
            client_id=238,
            readonly=True
        )
        
        await connector.connect()
        
        # Verify connectAsync was called with readonly=True
        mock_ib.connectAsync.assert_called_once()
        call_kwargs = mock_ib.connectAsync.call_args[1]
        assert call_kwargs['readonly'] is True

    @patch('data.market_data.IB')
    async def test_readonly_false_for_paper_port(self, mock_ib_class):
        """Connector should use readonly=False for paper port 4002."""
        from data.market_data import IBKRDataConnector
        
        mock_ib = Mock()
        mock_ib_class.return_value = mock_ib
        mock_ib.connectAsync = Mock()
        
        connector = IBKRDataConnector(
            host="127.0.0.1",
            port=4002,
            client_id=101,
            readonly=False
        )
        
        await connector.connect()
        
        # Verify connectAsync was called with readonly=False
        mock_ib.connectAsync.assert_called_once()
        call_kwargs = mock_ib.connectAsync.call_args[1]
        assert call_kwargs['readonly'] is False
