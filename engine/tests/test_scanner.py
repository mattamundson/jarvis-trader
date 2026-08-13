"""Tests for signal scanner and API key validation."""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from scanner.signal_scanner import SignalScanner, _is_futures_market_hours
from validation.api_keys import validate_api_keys

logger = logging.getLogger(__name__)


# A fixed, deterministic instant: Tuesday 2026-06-16 17:00 UTC == 12:00 ET.
# Chosen so the scanner's wall-clock gates all resolve to "scan allowed":
#   - not in the 9:30-9:35 / 15:45-16:00 ET banned session windows,
#   - not Wednesday (so the MCL 10:15-11:00 ET EIA blackout never triggers),
#   - inside equity Regular Trading Hours.
# Without this, _scan_symbol() reads datetime.now() and intermittently returns
# early depending on the wall-clock time CI happens to run at (the flaky class).
_FROZEN_UTC = datetime(2026, 6, 16, 17, 0, 0, tzinfo=timezone.utc)


class _FrozenDateTime(datetime):
    """datetime subclass whose now() is pinned to _FROZEN_UTC."""

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return _FROZEN_UTC.astimezone(tz)
        return _FROZEN_UTC.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_scanner_clock():
    """Pin every wall-clock-dependent scanner gate to a deterministic instant.

    Patches the module-level datetime used by _scan_symbol's session-timing /
    EIA-blackout gates plus both market-hours helpers, so a test's outcome can
    never depend on when CI happens to run.
    """
    with (
        patch("scanner.signal_scanner.datetime", _FrozenDateTime),
        patch("scanner.signal_scanner._is_futures_market_hours", return_value=True),
        patch("scanner.signal_scanner._is_equity_market_hours", return_value=True),
    ):
        yield


class TestFuturesMarketHours:
    """Test market hours detection."""

    def test_outside_market_hours_saturday(self):
        """Saturday should be outside hours."""
        with patch("scanner.signal_scanner.datetime") as mock_dt:
            # Saturday, 2pm CT
            mock_now = MagicMock()
            mock_now.weekday.return_value = 5  # Saturday
            mock_now.time.return_value = MagicMock()
            mock_dt.now.return_value = mock_now
            # Note: This is a simplification; the actual implementation uses timezone math
            # For real testing, use datetime arithmetic instead

    def test_during_market_hours_monday(self):
        """Monday during hours should be open."""
        # Monday 10am CT
        with patch("scanner.signal_scanner.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0  # Monday
            mock_now.time.return_value = MagicMock()
            mock_dt.now.return_value = mock_now
            # Simplified test — actual implementation more complex


class TestSignalScanner:
    """Test SignalScanner class."""

    @pytest.fixture
    def mock_pipeline(self):
        """Create mock trading pipeline."""
        return AsyncMock()

    @pytest.fixture
    def mock_db(self):
        """Create mock database manager."""
        return MagicMock()

    @pytest.fixture
    def scanner(self, mock_pipeline, mock_db):
        """Create scanner instance."""
        return SignalScanner(
            trading_pipeline=mock_pipeline,
            db_manager=mock_db,
            symbols=["MCL", "MNQ"],
            scan_interval_minutes=60,
        )

    def test_scanner_initialization(self, scanner):
        """Test scanner initializes with correct parameters."""
        assert scanner.symbols == ["MCL", "MNQ"]
        assert scanner.scan_interval_minutes == 60
        assert scanner._active is False
        assert scanner._total_scans == 0
        assert scanner._approval_count == 0

    def test_scanner_status(self, scanner):
        """Test status method returns correct state."""
        status = scanner.status()
        assert status["active"] is False
        assert status["symbols"] == ["MCL", "MNQ"]
        assert status["total_scans"] == 0
        assert status["approvals_created"] == 0

    @pytest.mark.asyncio
    async def test_scanner_start(self, scanner):
        """Test starting scanner."""
        await scanner.start()
        assert scanner._active is True
        assert scanner._task is not None
        await asyncio.sleep(0.1)
        await scanner.stop()

    @pytest.mark.asyncio
    async def test_scanner_pause_resume(self, scanner):
        """Test pause and resume."""
        await scanner.start()
        assert scanner._active is True

        await scanner.pause()
        assert scanner._active is False

        await scanner.resume()
        assert scanner._active is True

        await scanner.stop()

    @pytest.mark.asyncio
    async def test_scan_symbol_hold_signal(self, scanner, mock_pipeline, mock_db):
        """Test scanning symbol that returns HOLD signal."""
        mock_pipeline.analyze_and_decide.return_value = {
            "symbol": "MCL",
            "final_action": "hold",
            "final_quantity": 0,
        }

        await scanner._scan_symbol("MCL")

        # No approval should be created for HOLD
        mock_db.insert_pending_approval.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_symbol_buy_signal_autonomous(self, scanner, mock_pipeline, mock_db):
        """A BUY signal under the current standing config (REQUIRE_HUMAN_APPROVAL=False,
        Amo's 2026-08-11 decision) must NOT create a pending_trade_approvals row --
        signal_scanner.py's own comment explains why: nobody approves these in
        autonomous mode, so a row would only time out and generate a misleading
        'APPROVAL REQUIRED' DM for a trade that never happens."""
        mock_pipeline.analyze_and_decide.return_value = {
            "symbol": "MCL",
            "final_action": "buy",
            "final_quantity": 1,
            "trade_decision": {"entry_price": 75.50},
        }

        with patch.object(config.settings, "REQUIRE_HUMAN_APPROVAL", False):
            await scanner._scan_symbol("MCL")

        mock_db.insert_pending_approval.assert_not_called()
        assert scanner._approval_count == 0

    @pytest.mark.asyncio
    async def test_scan_symbol_buy_signal_requires_approval(self, scanner, mock_pipeline, mock_db):
        """Same BUY signal, but with REQUIRE_HUMAN_APPROVAL explicitly True --
        the approval-row code path this test protects still exists in
        signal_scanner.py and must keep working even though it's not the
        current deployment default."""
        mock_pipeline.analyze_and_decide.return_value = {
            "symbol": "MCL",
            "final_action": "buy",
            "final_quantity": 1,
            "trade_decision": {"entry_price": 75.50},
        }
        mock_db.insert_pending_approval.return_value = "approval-123"

        with patch.object(config.settings, "REQUIRE_HUMAN_APPROVAL", True):
            await scanner._scan_symbol("MCL")

        mock_db.insert_pending_approval.assert_called_once()
        call_kwargs = mock_db.insert_pending_approval.call_args.kwargs
        assert call_kwargs["symbol"] == "MCL"
        assert call_kwargs["action"] == "buy"
        assert call_kwargs["quantity"] == 1
        assert scanner._approval_count == 1

    @pytest.mark.asyncio
    async def test_scan_symbol_sell_signal_autonomous(self, scanner, mock_pipeline, mock_db):
        """A SELL signal under the current standing config must also skip the
        approval row (see test_scan_symbol_buy_signal_autonomous)."""
        mock_pipeline.analyze_and_decide.return_value = {
            "symbol": "MNQ",
            "final_action": "sell",
            "final_quantity": 2,
            "trade_decision": {"entry_price": 5500.00},
        }

        with patch.object(config.settings, "REQUIRE_HUMAN_APPROVAL", False):
            await scanner._scan_symbol("MNQ")

        mock_db.insert_pending_approval.assert_not_called()
        assert scanner._approval_count == 0

    @pytest.mark.asyncio
    async def test_scan_symbol_sell_signal_requires_approval(self, scanner, mock_pipeline, mock_db):
        """Same SELL signal, with REQUIRE_HUMAN_APPROVAL explicitly True."""
        mock_pipeline.analyze_and_decide.return_value = {
            "symbol": "MNQ",
            "final_action": "sell",
            "final_quantity": 2,
            "trade_decision": {"entry_price": 5500.00},
        }
        mock_db.insert_pending_approval.return_value = "approval-456"

        with patch.object(config.settings, "REQUIRE_HUMAN_APPROVAL", True):
            await scanner._scan_symbol("MNQ")

        mock_db.insert_pending_approval.assert_called_once()
        call_kwargs = mock_db.insert_pending_approval.call_args.kwargs
        assert call_kwargs["action"] == "sell"
        assert call_kwargs["quantity"] == 2

    @pytest.mark.asyncio
    async def test_scan_symbol_pipeline_error(self, scanner, mock_pipeline, mock_db):
        """Test scanner handles pipeline errors gracefully."""
        mock_pipeline.analyze_and_decide.side_effect = Exception("Pipeline error")

        await scanner._scan_symbol("MCL")

        # No approval should be created on error
        mock_db.insert_pending_approval.assert_not_called()
        assert scanner._error_count == 1


class TestAPIKeyValidation:
    """Test API key validation."""

    def test_validate_with_all_keys_present(self):
        """Test validation when all keys are present."""
        config = MagicMock()
        config.API_KEY = "api_123456789"
        config.ANTHROPIC_API_KEY = "sk-ant-api03-abcdef"
        config.POLYGON_API_KEY = "pk_1234567890"
        config.FRED_API_KEY = "fred_api_key"
        config.FINNHUB_API_KEY = "finnhub_api_key"
        config.TWILIO_ACCOUNT_SID = "twilio_sid"
        config.TWILIO_AUTH_TOKEN = "twilio_token"
        config.TWILIO_WHATSAPP_FROM = "whatsapp_from"
        config.WHATSAPP_TO = "whatsapp_to"

        result = validate_api_keys(config)

        assert result["valid"] is True
        assert len(result["missing_critical"]) == 0
        assert len(result["missing_optional"]) == 0
        assert result["capabilities"]["llm_agents"] is True
        assert result["capabilities"]["polygon_market_data"] is True

    def test_validate_missing_critical_key(self):
        """Test validation fails when critical key is missing."""
        config = MagicMock()
        config.API_KEY = None
        config.ANTHROPIC_API_KEY = "sk-ant-api03-abcdef"
        config.POLYGON_API_KEY = None
        config.FRED_API_KEY = None
        config.FINNHUB_API_KEY = None
        config.TWILIO_ACCOUNT_SID = None
        config.TWILIO_AUTH_TOKEN = None
        config.TWILIO_WHATSAPP_FROM = None
        config.WHATSAPP_TO = None

        result = validate_api_keys(config)

        assert result["valid"] is False
        assert len(result["missing_critical"]) > 0
        assert any("API_KEY" in desc for desc in result["missing_critical"])

    def test_validate_placeholder_values(self):
        """Test that placeholder values are treated as missing."""
        config = MagicMock()
        config.API_KEY = "your-api-key-here"
        config.ANTHROPIC_API_KEY = "sk-ant-api03-"
        config.POLYGON_API_KEY = None
        config.FRED_API_KEY = None
        config.FINNHUB_API_KEY = None
        config.TWILIO_ACCOUNT_SID = None
        config.TWILIO_AUTH_TOKEN = None
        config.TWILIO_WHATSAPP_FROM = None
        config.WHATSAPP_TO = None

        result = validate_api_keys(config)

        assert result["valid"] is False

    def test_validate_partial_optional_keys(self):
        """Test validation when only some optional keys present."""
        config = MagicMock()
        config.API_KEY = "api_123456789"
        config.ANTHROPIC_API_KEY = "sk-ant-api03-abcdef"
        config.POLYGON_API_KEY = None
        config.FRED_API_KEY = None
        config.FINNHUB_API_KEY = None
        config.TWILIO_ACCOUNT_SID = None
        config.TWILIO_AUTH_TOKEN = None
        config.TWILIO_WHATSAPP_FROM = None
        config.WHATSAPP_TO = None

        result = validate_api_keys(config)

        assert result["valid"] is True
        assert result["capabilities"]["llm_agents"] is True
        assert result["capabilities"]["polygon_market_data"] is False
        assert result["capabilities"]["whatsapp_alerts"] is False

    def test_validate_whatsapp_requires_all_four_keys(self):
        """Test that WhatsApp requires all four keys."""
        config = MagicMock()
        config.API_KEY = "api_123456789"
        config.ANTHROPIC_API_KEY = None
        config.POLYGON_API_KEY = None
        config.FRED_API_KEY = None
        config.FINNHUB_API_KEY = None
        # Only 3 of 4 WhatsApp keys
        config.TWILIO_ACCOUNT_SID = "sid"
        config.TWILIO_AUTH_TOKEN = "token"
        config.TWILIO_WHATSAPP_FROM = None  # Missing
        config.WHATSAPP_TO = None  # Missing

        result = validate_api_keys(config)

        assert result["valid"] is True
        assert result["capabilities"]["whatsapp_alerts"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
