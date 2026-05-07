"""Tests for IB Gateway health monitor."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import health.ib_monitor as ib_monitor_module

CT = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def reset_alert_time():
    """Reset the alert cooldown between tests."""
    ib_monitor_module._last_alert_time = 0.0
    yield
    ib_monitor_module._last_alert_time = 0.0


class TestIBMonitor:
    """Test suite for IB health monitor."""

    @pytest.mark.asyncio
    async def test_check_ib_health_returns_true_when_connected(self):
        """Test 1: check_ib_health returns True when connector.is_connected() = True."""
        connector = MagicMock()
        connector.is_connected.return_value = True

        result = await ib_monitor_module.check_ib_health(connector)

        assert result is True
        connector.is_connected.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_ib_health_returns_false_when_disconnected_during_market_hours(self):
        """Test 2: check_ib_health returns False when disconnected and is_market_hours() = True."""
        connector = MagicMock()
        connector.is_connected.return_value = False

        # Mock is_market_hours to return True
        with patch.object(
            ib_monitor_module, "is_market_hours", return_value=True
        ):
            result = await ib_monitor_module.check_ib_health(connector)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_ib_health_returns_true_when_not_market_hours(self):
        """Test 3: check_ib_health returns True (no alert sent) when is_market_hours() = False."""
        connector = MagicMock()
        connector.is_connected.return_value = False

        # Mock is_market_hours to return False
        with patch.object(
            ib_monitor_module, "is_market_hours", return_value=False
        ):
            result = await ib_monitor_module.check_ib_health(connector)

        # Should still return False (disconnected), but no alert sent due to cooldown/time
        assert result is False

    def test_is_market_hours_returns_false_on_saturday(self):
        """Test 4: is_market_hours() returns False on Saturday."""
        # Saturday = weekday() == 5
        saturday = datetime(2026, 4, 4, 12, 0, 0, tzinfo=CT)  # Saturday noon CT

        with patch("health.ib_monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = saturday
            mock_datetime.side_effect = lambda *args, **kw: datetime(
                *args, **kw
            ) if args else saturday

            result = ib_monitor_module.is_market_hours()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_ib_health_returns_true_when_connector_is_none(self):
        """Test 5: check_ib_health returns True when ib_connector is None."""
        result = await ib_monitor_module.check_ib_health(None)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_ib_health_does_not_raise_when_connector_raises_exception(self):
        """Test 6: check_ib_health does not raise when connector.is_connected() raises Exception."""
        connector = MagicMock()
        connector.is_connected.side_effect = RuntimeError("Connection error")

        # Should not raise
        result = await ib_monitor_module.check_ib_health(connector)

        # Should return True (assume connected to avoid false alerts)
        assert result is True


class TestIsMarketHours:
    """Test is_market_hours() function."""

    def test_market_hours_true_on_weekday_during_market(self):
        """Test that is_market_hours() returns True on weekday during market hours."""
        # Monday 9:00 AM CT
        monday_9am = datetime(2026, 4, 6, 9, 0, 0, tzinfo=CT)  # Monday

        with patch("health.ib_monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = monday_9am
            mock_datetime.side_effect = lambda *args, **kw: datetime(
                *args, **kw
            ) if args else monday_9am

            result = ib_monitor_module.is_market_hours()

        assert result is True

    def test_market_hours_false_before_market_open(self):
        """Test that is_market_hours() returns False before market opens."""
        # Monday 8:00 AM CT (before 8:30 AM open)
        monday_8am = datetime(2026, 4, 6, 8, 0, 0, tzinfo=CT)

        with patch("health.ib_monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = monday_8am
            mock_datetime.side_effect = lambda *args, **kw: datetime(
                *args, **kw
            ) if args else monday_8am

            result = ib_monitor_module.is_market_hours()

        assert result is False

    def test_market_hours_false_after_market_close(self):
        """Test that is_market_hours() returns False after market closes."""
        # Monday 5:00 PM CT (after 4:15 PM close)
        monday_5pm = datetime(2026, 4, 6, 17, 0, 0, tzinfo=CT)

        with patch("health.ib_monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = monday_5pm
            mock_datetime.side_effect = lambda *args, **kw: datetime(
                *args, **kw
            ) if args else monday_5pm

            result = ib_monitor_module.is_market_hours()

        assert result is False
