"""Cooldown regression for POST /notifications/vix-alert-check.

The dashboard's VIXRegimeCard (dashboard/components/VIXRegimeCard.tsx) polls
this endpoint every 5 minutes purely to *read* the current VIX value for
display. Before the fix, every poll had the live side effect of re-sending a
real WhatsApp alert whenever VIX was elevated, so an open watchlist tab
spammed the same alert every 5 minutes. Exercises routers.notifications_router
directly (no full app boot) — mirrors the lightweight-unit-test style used for
notifications.pipeline_alert_cooldown.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from notifications.vix_alert_cooldown import reset_vix_alert_cooldown_for_tests
from routers.notifications_router import check_vix_alert


@dataclass
class _FakeVixState:
    vix_value: float
    regime: str = "EXTREME"
    classification: str = "EXTREME"
    source: str = "stub"


class _FakeVIXOverlay:
    def __init__(self, vix_value: float) -> None:
        self._state = _FakeVixState(vix_value=vix_value)

    def get_state(self) -> _FakeVixState:
        return self._state


@pytest.fixture(autouse=True)
def _reset_cooldown():
    reset_vix_alert_cooldown_for_tests()
    yield
    reset_vix_alert_cooldown_for_tests()


@pytest.mark.asyncio
async def test_second_poll_within_cooldown_does_not_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    import analytics.vix_overlay as vix_overlay_mod

    monkeypatch.setattr(vix_overlay_mod, "VIXOverlay", lambda: _FakeVIXOverlay(45.0))

    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("notifications.whatsapp.send_whatsapp_message", send_mock)

    first = await check_vix_alert()
    second = await check_vix_alert()

    assert first["sent"] is True
    assert second["sent"] is False
    assert second["reason"] == "cooldown_active"
    # Exactly one real WhatsApp send across two polls, simulating the
    # dashboard's 5-minute VIXRegimeCard refresh while VIX stays elevated.
    assert send_mock.await_count == 1


@pytest.mark.asyncio
async def test_normal_vix_never_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    import analytics.vix_overlay as vix_overlay_mod

    monkeypatch.setattr(vix_overlay_mod, "VIXOverlay", lambda: _FakeVIXOverlay(15.0))

    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("notifications.whatsapp.send_whatsapp_message", send_mock)

    result = await check_vix_alert()

    assert result["sent"] is False
    assert result["reason"] == "VIX normal — no alert needed"
    send_mock.assert_not_awaited()
