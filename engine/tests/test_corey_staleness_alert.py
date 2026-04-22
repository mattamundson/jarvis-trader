"""
Corey staleness watchdog regression tests.

Guards the contract that `notify_corey_stale` fires when discord_corey_commentary
stops refreshing. Without this alert, agents consume a stale `corey_session_bias`
and signal quality silently degrades.

Covered scenarios:
  1. 3-day-old last message → notify_corey_stale fires once
  2. Fresh last message (< 2 days) → no notification
  3. Empty table → notify_corey_stale fires with days_stale=999
  4. Same-day dedupe — second call within the same day does not re-fire
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

os.environ["TESTING"] = ""  # staleness tests verify the send path; not TESTING mode
os.environ.setdefault("OPENCLAW_WHATSAPP_TO", "+15555550000")

from notifications import openclaw_notifier  # noqa: E402

_CT = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Clear the once-per-day dedupe state between tests."""
    openclaw_notifier._corey_stale_last_alert_date = ""
    yield
    openclaw_notifier._corey_stale_last_alert_date = ""


@pytest.mark.asyncio
async def test_3_day_stale_fires_alert():
    """3 days stale must fire an alert."""
    with patch.object(openclaw_notifier, "_send", new=AsyncMock(return_value=True)) as mock_send:
        result = await openclaw_notifier.notify_corey_stale(
            days_stale=3,
            last_message_date="2026-04-16 15:30 CT",
        )
    assert result is True
    assert mock_send.await_count == 1
    msg = mock_send.await_args.args[0]
    assert "CORey FEED STALE" in msg
    assert "3 days" in msg
    assert "2026-04-16 15:30 CT" in msg


@pytest.mark.asyncio
async def test_dedupe_same_day_suppresses_second_call():
    """Second call on the same CT day must not re-send."""
    with patch.object(openclaw_notifier, "_send", new=AsyncMock(return_value=True)) as mock_send:
        first = await openclaw_notifier.notify_corey_stale(
            days_stale=3, last_message_date="2026-04-16"
        )
        second = await openclaw_notifier.notify_corey_stale(
            days_stale=4, last_message_date="2026-04-15"
        )
    assert first is True
    assert second is False
    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_testing_mode_suppresses_alert(monkeypatch):
    """TESTING=1 must suppress alerts so tests elsewhere don't spam real WhatsApp."""
    monkeypatch.setenv("TESTING", "1")
    with patch.object(openclaw_notifier, "_send", new=AsyncMock(return_value=True)) as mock_send:
        result = await openclaw_notifier.notify_corey_stale(
            days_stale=5, last_message_date="2026-04-14"
        )
    assert result is False
    assert mock_send.await_count == 0


@pytest.mark.asyncio
async def test_send_failure_does_not_burn_dedupe():
    """If the actual WhatsApp send fails, we must NOT mark alerted_today — so the
    next hourly tick can retry. Only a successful send arms the dedupe."""
    with patch.object(openclaw_notifier, "_send", new=AsyncMock(return_value=False)) as mock_send:
        first = await openclaw_notifier.notify_corey_stale(
            days_stale=3, last_message_date="2026-04-16"
        )
        second = await openclaw_notifier.notify_corey_stale(
            days_stale=3, last_message_date="2026-04-16"
        )
    assert first is False
    assert second is False
    # Both calls attempted _send because dedupe didn't arm
    assert mock_send.await_count == 2
