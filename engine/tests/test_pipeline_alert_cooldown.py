"""Tests for pipeline WhatsApp cooldown decision logic and alert_log on suppress."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from notifications.pipeline_alert_cooldown import (
    pipeline_alert_cooldown_timedelta,
    pipeline_alert_decision,
    reset_pipeline_alert_cooldown_for_tests,
)


def test_pipeline_alert_cooldown_timedelta_clamps_to_one_minute() -> None:
    assert pipeline_alert_cooldown_timedelta(0) == timedelta(minutes=1)
    assert pipeline_alert_cooldown_timedelta(30) == timedelta(minutes=30)


def test_decision_send_when_never_sent_and_notifier_on() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        pipeline_alert_decision(
            last_sent=None,
            now=now,
            cooldown_minutes=15,
            notifier_enabled=True,
        )
        == "send"
    )


def test_decision_suppressed_cooldown() -> None:
    now = datetime(2026, 1, 1, 12, 5, 0)
    last = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        pipeline_alert_decision(
            last_sent=last,
            now=now,
            cooldown_minutes=15,
            notifier_enabled=True,
        )
        == "suppressed_cooldown"
    )


def test_decision_send_after_cooldown_elapsed() -> None:
    now = datetime(2026, 1, 1, 12, 20, 0)
    last = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        pipeline_alert_decision(
            last_sent=last,
            now=now,
            cooldown_minutes=15,
            notifier_enabled=True,
        )
        == "send"
    )


def test_decision_whatsapp_disabled() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        pipeline_alert_decision(
            last_sent=None,
            now=now,
            cooldown_minutes=15,
            notifier_enabled=False,
        )
        == "suppressed_no_channel"
    )


@pytest.mark.asyncio
async def test_deliver_logs_sent_then_suppressed_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two rapid BUY signals → one Twilio send + two alert_log rows (sent + suppressed_cooldown)."""
    reset_pipeline_alert_cooldown_for_tests()

    # main imports optional Gemini analysis wiring through services.jarvis_analysis.
    # This test only needs the WhatsApp delivery helper, so keep the import offline.
    with patch.dict(
        sys.modules,
        {
            "google": MagicMock(),
            "google.genai": MagicMock(),
            "services.jarvis_analysis": MagicMock(),
        },
    ):
        import main as main_mod

        monkeypatch.setattr(main_mod.settings, "ALERT_COOLDOWN_MINUTES", 60)

        calls: list[dict] = []

        mock_db = MagicMock()

        def _capture(**kwargs: object) -> int:
            calls.append(dict(kwargs))
            return len(calls)

        mock_db.insert_alert_log = _capture
        monkeypatch.setattr(main_mod, "db_manager", mock_db)

        notifier = MagicMock()
        notifier.enabled = True
        notifier.send = AsyncMock(return_value=True)

        with patch("notifications.whatsapp.get_notifier", return_value=notifier):
            await main_mod._deliver_pipeline_whatsapp_if_eligible(
                symbol="MES",
                action="buy",
                qty=1,
                price_info=5000.0,
                reasoning="test",
                confidence=0.7,
            )
            await main_mod._deliver_pipeline_whatsapp_if_eligible(
                symbol="MES",
                action="buy",
                qty=1,
                price_info=5000.0,
                reasoning="test",
                confidence=0.7,
            )

    assert notifier.send.await_count == 1
    assert len(calls) == 2
    assert calls[0]["status"] == "sent"
    assert calls[1]["status"] == "suppressed_cooldown"
    assert calls[1]["symbol"] == "MES"
