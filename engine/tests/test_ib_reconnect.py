"""
JARVIS TRADER — IB Gateway Connection Resilience Tests

Tests for auto-reconnect with exponential backoff, connection state enum,
heartbeat monitoring, and SafetyLayer notification.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConnectionStateEnum:
    """ConnectionState enum validation."""

    def test_connection_state_values(self):
        """ConnectionState enum has required states."""
        from execution.ib_gateway_connector import ConnectionState

        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.DISCONNECTING.value == "disconnecting"
        assert ConnectionState.RECONNECTING.value == "reconnecting"
        assert ConnectionState.FAILED.value == "failed"

    def test_connection_state_enum_members(self):
        """ConnectionState has all 4 required members."""
        from execution.ib_gateway_connector import ConnectionState

        states = {s.name for s in ConnectionState}
        assert states == {"CONNECTED", "DISCONNECTING", "RECONNECTING", "FAILED"}


class TestConnectionStateInitialization:
    """Initial connection state setup."""

    def test_connector_initial_state_failed(self, settings, safety_layer_mock):
        """Connector starts in FAILED state."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings, safety_layer_mock)
        assert connector._connection_state == ConnectionState.FAILED
        assert connector._reconnect_attempts == 0
        assert connector._last_heartbeat is None

    def test_connector_initial_not_connected(self, settings, safety_layer_mock):
        """Connector starts disconnected."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings, safety_layer_mock)
        assert connector.is_connected() is False


class TestConnectStateTransition:
    """State transitions on successful connect."""

    @pytest.mark.asyncio
    async def test_connect_sets_connected_state(self, settings_paper, safety_layer_mock):
        """Successful connect sets state to CONNECTED."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        result = await connector.connect()

        assert result is True
        assert connector._connection_state == ConnectionState.CONNECTED
        assert connector.is_connected() is True

    @pytest.mark.asyncio
    async def test_connect_resets_reconnect_attempts(self, settings_paper, safety_layer_mock):
        """Successful connect resets reconnect attempt counter."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 5
        result = await connector.connect()

        assert result is True
        assert connector._reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_connect_starts_heartbeat(self, settings_paper, safety_layer_mock):
        """Successful connect starts heartbeat task."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        result = await connector.connect()

        assert result is True
        assert connector._heartbeat_task is not None
        assert not connector._heartbeat_task.done()

        # Cleanup
        await connector.disconnect()


class TestDisconnectStateTransition:
    """State transitions on disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_sets_failed_state(self, settings_paper, safety_layer_mock):
        """Disconnect sets state to FAILED."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        await connector.connect()
        result = await connector.disconnect()

        assert result is True
        assert connector._connection_state == ConnectionState.FAILED
        assert connector.is_connected() is False

    @pytest.mark.asyncio
    async def test_disconnect_cancels_heartbeat(self, settings_paper, safety_layer_mock):
        """Disconnect cancels the heartbeat task."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        await connector.connect()
        heartbeat_task = connector._heartbeat_task

        assert heartbeat_task is not None
        assert not heartbeat_task.done()

        await connector.disconnect()
        await asyncio.sleep(0.1)  # Let cancellation propagate

        assert heartbeat_task.done()


class TestReconnectExponentialBackoff:
    """Reconnect logic with exponential backoff: 2s, 4s, 8s."""

    @pytest.mark.asyncio
    async def test_reconnect_attempt_1_backoff(self, settings_paper, safety_layer_mock):
        """First reconnect attempt waits 2 seconds (2^1)."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 0

        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            # Mock the second connect call to return True
            with patch.object(connector, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = True
                result = await connector._reconnect()

                mock_sleep.assert_called_once()
                sleep_seconds = mock_sleep.call_args[0][0]
                assert sleep_seconds == 2  # 2^1

    @pytest.mark.asyncio
    async def test_reconnect_attempt_2_backoff(self, settings_paper, safety_layer_mock):
        """Second reconnect attempt waits 4 seconds (2^2)."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 1

        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with patch.object(connector, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = True
                result = await connector._reconnect()

                sleep_seconds = mock_sleep.call_args[0][0]
                assert sleep_seconds == 4  # 2^2

    @pytest.mark.asyncio
    async def test_reconnect_attempt_3_backoff(self, settings_paper, safety_layer_mock):
        """Third reconnect attempt waits 8 seconds (2^3)."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 2

        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with patch.object(connector, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = True
                result = await connector._reconnect()

                sleep_seconds = mock_sleep.call_args[0][0]
                assert sleep_seconds == 8  # 2^3

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts_exhausted(self, settings_paper, safety_layer_mock):
        """Reconnect fails after max attempts (3) exhausted."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 3

        result = await connector._reconnect()

        assert result is False
        assert connector._connection_state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_reconnect_success_increments_counter(self, settings_paper, safety_layer_mock):
        """Successful reconnect increments attempt counter."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 0

        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with patch.object(connector, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = True
                result = await connector._reconnect()

                assert result is True
                assert connector._reconnect_attempts == 1


class TestHeartbeatMonitoring:
    """Heartbeat monitoring and disconnection detection."""

    @pytest.mark.asyncio
    async def test_heartbeat_interval_5_seconds(self, settings_paper, safety_layer_mock):
        """Heartbeat checks connection every 5 seconds (paired with 15s deadman-switch threshold)."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        await connector.connect()

        with patch("asyncio.sleep") as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError()

            try:
                await connector._heartbeat()
            except asyncio.CancelledError:
                pass

            mock_sleep.assert_called_once_with(5)

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_detects_disconnection(self, settings_paper, safety_layer_mock):
        """Heartbeat detects disconnection and triggers reconnect."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        await connector.connect()

        # Simulate disconnection
        connector._connected = False

        with patch("asyncio.sleep") as mock_sleep:
            with patch.object(connector, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
                mock_reconnect.return_value = True
                mock_sleep.side_effect = asyncio.CancelledError()

                try:
                    await connector._heartbeat()
                except asyncio.CancelledError:
                    pass

                # Verify reconnect was called
                mock_reconnect.assert_called_once()

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_task_cancellation(self, settings_paper, safety_layer_mock):
        """Heartbeat task can be cancelled gracefully."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        await connector.connect()

        heartbeat_task = connector._heartbeat_task
        assert heartbeat_task is not None

        await connector.disconnect()
        await asyncio.sleep(0.1)

        assert heartbeat_task.done()


class TestSafetyLayerNotification:
    """SafetyLayer notification on connection state changes."""

    @pytest.mark.asyncio
    async def test_notify_connection_state_on_connect(self, settings_paper, safety_layer_mock):
        """SafetyLayer is notified when connection established."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        safety_layer_mock.on_connection_state_change = MagicMock()
        connector = IBGatewayConnector(settings_paper, safety_layer_mock)

        await connector.connect()

        safety_layer_mock.on_connection_state_change.assert_called()
        call_args = safety_layer_mock.on_connection_state_change.call_args[0][0]
        assert call_args == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_notify_connection_state_on_disconnect(self, settings_paper, safety_layer_mock):
        """SafetyLayer is notified when connection lost."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        safety_layer_mock.on_connection_state_change = MagicMock()
        connector = IBGatewayConnector(settings_paper, safety_layer_mock)

        await connector.connect()
        await connector.disconnect()

        # Should have been called twice: once for CONNECTED, once for FAILED
        assert safety_layer_mock.on_connection_state_change.call_count >= 2

    @pytest.mark.asyncio
    async def test_notify_connection_state_graceful_fallback(
        self, settings_paper, safety_layer_mock
    ):
        """Notification failure doesn't crash connector."""
        from execution.ib_gateway_connector import IBGatewayConnector

        # Mock SafetyLayer method to raise exception
        safety_layer_mock.on_connection_state_change = MagicMock(
            side_effect=Exception("SafetyLayer error")
        )
        connector = IBGatewayConnector(settings_paper, safety_layer_mock)

        # Should not raise exception
        result = await connector.connect()
        assert result is True


class TestOnDisconnectCallback:
    """Callback registration for disconnect events."""

    def test_set_on_disconnect_callback(self, settings, safety_layer_mock):
        """Callback can be registered."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings, safety_layer_mock)
        callback = MagicMock()

        connector.set_on_disconnect_callback(callback)

        assert connector._on_disconnect_callback == callback

    def test_callback_registration_accepts_callable(self, settings, safety_layer_mock):
        """Callback accepts any callable."""
        from execution.ib_gateway_connector import IBGatewayConnector

        connector = IBGatewayConnector(settings, safety_layer_mock)

        def my_callback(state):
            pass

        connector.set_on_disconnect_callback(my_callback)
        assert connector._on_disconnect_callback == my_callback


class TestConnectionStateRecovery:
    """Connection state after various failure scenarios."""

    @pytest.mark.asyncio
    async def test_live_mode_sets_failed_state(self, settings_live, safety_layer_mock):
        """Live mode (not implemented) sets FAILED state."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings_live, safety_layer_mock)
        result = await connector.connect()

        assert result is False
        assert connector._connection_state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_reconnect_state_transitions(self, settings_paper, safety_layer_mock):
        """State transitions through RECONNECTING before CONNECTED."""
        from execution.ib_gateway_connector import ConnectionState, IBGatewayConnector

        connector = IBGatewayConnector(settings_paper, safety_layer_mock)
        connector._reconnect_attempts = 0

        with patch("asyncio.sleep"):
            with patch.object(connector, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = True

                result = await connector._reconnect()

                assert result is True
                assert connector._connection_state == ConnectionState.CONNECTED
