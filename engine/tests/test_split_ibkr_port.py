"""
Tests for split IBKR port configuration (market data on 4001, execution on 4002).

Verifies:
- Market data connections can use 4001 when IBKR_MARKET_DATA_PORT is set
- Execution connections still reject 4001
- Default behavior unchanged when split-port settings not configured
- Startup checks pass with split-port config
- No orders can be placed through the market data connection when on a live port
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock, patch

import pytest

from config import TradingConfig
from data.market_data import resolve_data_client_id
from startup_checks import _check_ibkr_port


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
        from data.market_data import IBKRDataConnector, MarketDataManager

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
        from data.market_data import IBKRDataConnector, MarketDataManager

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

        # Data port check (mirrors execution when not configured, separate when configured)
        data_alive, data_port = _check_ibgateway_data_port_alive(exec_alive, exec_port)
        assert isinstance(data_alive, bool)
        assert isinstance(data_port, int)

    @pytest.mark.parametrize("split_config,expected_data_port,expected_same", [
        (None, 4002, True),    # Non-split: data fields mirror execution (4002)
        (4001, 4001, False),   # Split: data port 4001 reported independently
    ])
    def test_health_endpoint_serializes_data_port_fields(self, split_config, expected_data_port, expected_same):
        """GET /health must include ibgateway_data_port and ibgateway_data_alive in response.

        Tests both non-split case (data fields equal execution fields) and split case
        (data port 4001 reported independently). Mocks TCP probes so tests don't depend
        on a live gateway.
        """
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from main import app

        # Mock both TCP probes to return consistent values
        with patch('routers.health_router._check_ibgateway_alive') as mock_exec, \
             patch('routers.health_router.settings') as mock_settings:

            # Execution port always returns (True, 4002)
            mock_exec.return_value = (True, 4002)

            # Configure split-port setting
            mock_settings.IBKR_MARKET_DATA_PORT = split_config

            client = TestClient(app)
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            # Verify all four fields exist and have correct types
            assert "ibgateway_port" in data
            assert "ibgateway_alive" in data
            assert "ibgateway_data_port" in data
            assert "ibgateway_data_alive" in data

            # Execution fields should always be present
            assert data["ibgateway_port"] == 4002
            assert data["ibgateway_alive"] is True

            # Data fields behavior depends on split-port config
            assert data["ibgateway_data_port"] == expected_data_port
            assert isinstance(data["ibgateway_data_alive"], bool)

            # In non-split mode, data fields should mirror execution
            if expected_same:
                assert data["ibgateway_data_port"] == data["ibgateway_port"]
                assert data["ibgateway_data_alive"] == data["ibgateway_alive"]
            else:
                # In split mode, data port should differ from execution port
                assert data["ibgateway_data_port"] != data["ibgateway_port"]


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

    @pytest.mark.asyncio
    async def test_guarded_ib_blocks_place_order_on_live_port(self):
        """GuardedIBWrapper should block placeOrder when on a live port."""
        from data.market_data import GuardedIBWrapper

        mock_ib = Mock()
        mock_ib.placeOrder = Mock()

        # Live port (4001) should block
        guarded = GuardedIBWrapper(mock_ib, 4001)
        with pytest.raises(RuntimeError, match="SAFETY BLOCK.*placeOrder.*not allowed.*live port 4001"):
            guarded.placeOrder(Mock(), Mock())

        # Paper port (4002) should allow through
        guarded_paper = GuardedIBWrapper(mock_ib, 4002)
        guarded_paper.placeOrder(Mock(), Mock())
        mock_ib.placeOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_guarded_ib_blocks_cancel_order_on_live_port(self):
        """GuardedIBWrapper should block cancelOrder when on a live port."""
        from data.market_data import GuardedIBWrapper

        mock_ib = Mock()
        mock_ib.cancelOrder = Mock()

        # Live port (4001) should block
        guarded = GuardedIBWrapper(mock_ib, 4001)
        with pytest.raises(RuntimeError, match="SAFETY BLOCK.*cancelOrder.*not allowed.*live port 4001"):
            guarded.cancelOrder(Mock())

        # TWS live port (7496) should also block
        guarded_tws = GuardedIBWrapper(mock_ib, 7496)
        with pytest.raises(RuntimeError, match="SAFETY BLOCK.*cancelOrder.*not allowed.*live port 7496"):
            guarded_tws.cancelOrder(Mock())

    @pytest.mark.asyncio
    async def test_guarded_ib_allows_readonly_operations(self):
        """GuardedIBWrapper should allow read-only operations on any port."""
        from data.market_data import GuardedIBWrapper

        mock_ib = Mock()
        mock_ib.qualifyContractsAsync = AsyncMock(return_value=[Mock()])
        mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
        mock_ib.isConnected = Mock(return_value=True)

        # Live port should allow read-only operations
        guarded = GuardedIBWrapper(mock_ib, 4001)
        await guarded.qualifyContractsAsync(Mock())
        await guarded.reqHistoricalDataAsync(Mock())
        assert guarded.isConnected()

        mock_ib.qualifyContractsAsync.assert_called_once()
        mock_ib.reqHistoricalDataAsync.assert_called_once()
        mock_ib.isConnected.assert_called_once()


class TestSmokeEndpointSafety:
    """Test safety blocks on the /safety/smoke/bracket endpoint."""

    @pytest.mark.asyncio
    async def test_smoke_endpoint_refuses_live_port(self):
        """Smoke endpoint should refuse to run when data port is on 4001."""
        from unittest.mock import patch

        from fastapi import HTTPException

        import main

        # Mock data_manager with ibkr on live port
        mock_ibkr = Mock()
        mock_ibkr.is_connected = True
        mock_ibkr._port = 4001

        mock_data_manager = Mock()
        mock_data_manager.ibkr = mock_ibkr

        with patch.object(main, 'data_manager', mock_data_manager):
            from routers.safety_router import smoke_bracket

            with pytest.raises(HTTPException) as exc_info:
                await smoke_bracket()

            assert exc_info.value.status_code == 400
            assert "SAFETY BLOCK" in exc_info.value.detail
            assert "4001" in exc_info.value.detail
            assert "live port" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_smoke_endpoint_allows_paper_port(self):
        """Smoke endpoint should allow paper port 4002."""
        from unittest.mock import AsyncMock, patch

        import main

        # Mock data_manager with ibkr on paper port
        mock_ib = Mock()
        mock_ib.qualifyContractsAsync = AsyncMock(return_value=[Mock(conId=12345)])
        mock_ib.placeOrder = Mock(return_value=Mock(order=Mock(orderId=1)))
        mock_ib.openTrades = Mock(return_value=[])
        mock_ib.cancelOrder = Mock()

        mock_ibkr = Mock()
        mock_ibkr.is_connected = True
        mock_ibkr._port = 4002
        mock_ibkr._ib = mock_ib
        mock_ibkr._resolve_front_month = AsyncMock(return_value=Mock())

        mock_data_manager = Mock()
        mock_data_manager.ibkr = mock_ibkr

        with patch.object(main, 'data_manager', mock_data_manager):
            from routers.safety_router import smoke_bracket

            # Should not raise for paper port
            result = await smoke_bracket()
            assert isinstance(result, dict)


class TestSourceCodeSafety:
    """Test that source code doesn't directly access _ib.client or _ib.wrapper outside allowed modules."""

    def test_no_forbidden_ib_client_wrapper_access(self):
        """Source files outside execution/ and data/market_data.py must not access ._ib.client or ._ib.wrapper."""
        import os
        import re

        # Pattern to match ._ib.client or ._ib.wrapper
        pattern = re.compile(r'\._ib\.(client|wrapper)')

        allowed_files = {
            'engine/data/market_data.py',
        }

        violations = []
        engine_root = os.path.join(os.path.dirname(__file__), '..')

        for root, dirs, files in os.walk(engine_root):
            # Skip test files, .venv, __pycache__, .git
            dirs[:] = [d for d in dirs if d not in ('.venv', '__pycache__', '.git', 'tests')]

            # Skip execution/ directory - it's allowed to use ._ib.client/wrapper
            if 'execution' in os.path.relpath(root, engine_root).split(os.sep):
                continue

            for filename in files:
                if not filename.endswith('.py'):
                    continue

                filepath = os.path.join(root, filename)
                relpath = os.path.relpath(filepath, engine_root)

                # Skip allowed files
                if any(relpath.endswith(allowed) for allowed in allowed_files):
                    continue

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            # Skip comments
                            if line.strip().startswith('#'):
                                continue
                            if pattern.search(line):
                                violations.append(f"{relpath}:{line_num}: {line.strip()}")
                except Exception:
                    pass

        if violations:
            pytest.fail(
                "Found forbidden ._ib.client or ._ib.wrapper access outside execution/ "
                "and data/market_data.py:\n" + "\n".join(violations)
            )


class TestGuardedIBWrapperWiring:
    """Test that GuardedIBWrapper is actually applied and blocks order operations."""

    @pytest.mark.asyncio
    async def test_guarded_wrapper_applied_on_live_port(self):
        """IBKRDataConnector on port 4001 should wrap _ib with GuardedIBWrapper."""
        from unittest.mock import AsyncMock, Mock

        from data.market_data import GuardedIBWrapper, IBKRDataConnector

        with patch('ib_async.IB') as mock_ib_class:
            mock_ib = Mock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.disconnectedEvent = Mock()
            mock_ib.reqMarketDataType = Mock()
            mock_ib.client = Mock()  # Mock the client attribute
            mock_ib_class.return_value = mock_ib

            connector = IBKRDataConnector(host="127.0.0.1", port=4001, readonly=True)
            await connector.connect()

            # Verify _ib is wrapped
            assert isinstance(connector._ib, GuardedIBWrapper)

            # Verify direct placeOrder is blocked
            with pytest.raises(RuntimeError, match="SAFETY BLOCK.*placeOrder.*live port 4001"):
                connector._ib.placeOrder(Mock(), Mock())

            # Verify client.placeOrder is also blocked
            with pytest.raises(RuntimeError, match="SAFETY BLOCK.*client.placeOrder.*live port 4001"):
                connector._ib.client.placeOrder(Mock(), Mock())

    @pytest.mark.asyncio
    async def test_guarded_wrapper_not_applied_on_paper_port(self):
        """IBKRDataConnector on port 4002 should wrap _ib but allow operations."""
        from unittest.mock import AsyncMock, Mock

        from data.market_data import GuardedIBWrapper, IBKRDataConnector

        with patch('ib_async.IB') as mock_ib_class:
            mock_ib = Mock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.disconnectedEvent = Mock()
            mock_ib.reqMarketDataType = Mock()
            mock_ib.placeOrder = Mock(return_value=Mock())
            mock_ib.client = Mock()
            mock_ib.client.placeOrder = Mock(return_value=Mock())
            mock_ib_class.return_value = mock_ib

            connector = IBKRDataConnector(host="127.0.0.1", port=4002)
            await connector.connect()

            # Verify _ib is wrapped (GuardedIBWrapper is always applied)
            assert isinstance(connector._ib, GuardedIBWrapper)

            # Verify operations are allowed on paper port
            connector._ib.placeOrder(Mock(), Mock())
            mock_ib.placeOrder.assert_called_once()

            connector._ib.client.placeOrder(Mock(), Mock())
            mock_ib.client.placeOrder.assert_called_once()

