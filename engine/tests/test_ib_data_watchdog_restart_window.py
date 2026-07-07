"""US-006 tests — IB Gateway daily restart-window awareness in the watchdog.

Inside the configured IBKR_GATEWAY_RESTART_WINDOW (local "HH:MM-HH:MM"):
  - alerts are suppressed (a drop there is routine, not an incident)
  - reconnect spacing is tightened (retry every interval, skip exponential backoff)
Outside it, behavior is unchanged.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from services.ib_data_watchdog import IBDataWatchdog, _parse_restart_window

# --- parsing ---------------------------------------------------------------

def test_parse_window_basic():
    assert _parse_restart_window("01:00-01:30") == (60, 90)


def test_parse_window_wraps_midnight():
    assert _parse_restart_window("23:50-00:10") == (23 * 60 + 50, 10)


@pytest.mark.parametrize("raw", [None, "", "   ", "nonsense", "01:00", "25:00-01:00", "01:70-02:00"])
def test_parse_window_invalid_or_blank_is_none(raw):
    assert _parse_restart_window(raw) is None


def test_parse_window_zero_width_is_none():
    assert _parse_restart_window("01:00-01:00") is None


# --- membership ------------------------------------------------------------

class _DMmin:
    """Minimal data-manager stub the watchdog accepts at construction."""
    def __init__(self):
        self.ibkr = None
        self._last_ibkr_data_ts = None
        self._watchdog = None


def _wd(monkeypatch, window=None, dm=None):
    if window is None:
        monkeypatch.delenv("IBKR_GATEWAY_RESTART_WINDOW", raising=False)
    else:
        monkeypatch.setenv("IBKR_GATEWAY_RESTART_WINDOW", window)
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_ENABLED", "0")  # never schedule a task
    return IBDataWatchdog(dm if dm is not None else _DMmin())


def test_membership_normal_window(monkeypatch):
    wd = _wd(monkeypatch, "01:00-01:30")
    assert wd._in_restart_window(now_minutes=75) is True
    assert wd._in_restart_window(now_minutes=60) is True   # inclusive start
    assert wd._in_restart_window(now_minutes=90) is False  # exclusive end
    assert wd._in_restart_window(now_minutes=30) is False


def test_membership_wrap_window(monkeypatch):
    wd = _wd(monkeypatch, "23:50-00:10")
    assert wd._in_restart_window(now_minutes=1435) is True   # 23:55
    assert wd._in_restart_window(now_minutes=1439) is True   # 23:59
    assert wd._in_restart_window(now_minutes=0) is True      # 00:00
    assert wd._in_restart_window(now_minutes=9) is True      # 00:09
    assert wd._in_restart_window(now_minutes=10) is False    # exclusive end
    assert wd._in_restart_window(now_minutes=700) is False


def test_membership_no_window_always_false(monkeypatch):
    wd = _wd(monkeypatch, None)
    assert wd.restart_window is None
    assert wd._in_restart_window(now_minutes=75) is False


def test_status_exposes_window(monkeypatch):
    wd = _wd(monkeypatch, "23:50-00:10")
    st = wd.status()
    assert st["restart_window"] == "23:50-00:10"
    assert "in_restart_window" in st


# --- alert suppression -----------------------------------------------------

class _Ibkr:
    def __init__(self, connected):
        self._c = connected

    @property
    def is_connected(self):
        return self._c


class _DM:
    def __init__(self, connected=True, reconnect_result=True, last_ts=None):
        self.ibkr = _Ibkr(connected)
        self._last_ibkr_data_ts = last_ts
        self.reconnect_calls = 0
        self._reconnect_result = reconnect_result
        self._watchdog = None

    async def reconnect_ibkr(self, timeout=15.0):
        self.reconnect_calls += 1
        if self._reconnect_result:
            self.ibkr._c = True
        return self._reconnect_result


@pytest.mark.asyncio
async def test_alert_suppressed_inside_window(monkeypatch):
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: True)
    notify = AsyncMock()
    monkeypatch.setattr("notifications.openclaw_notifier.notify_ib_disconnect", notify)

    wd = _wd(monkeypatch, "01:00-01:30")
    wd.consecutive_failures = 5
    monkeypatch.setattr(wd, "_in_restart_window", lambda now_minutes=None: True)
    wd._maybe_alert()
    await asyncio.sleep(0)
    assert notify.call_count == 0
    assert wd._last_alert == 0.0  # untouched → not suppressing the cooldown either


@pytest.mark.asyncio
async def test_alert_fires_outside_window(monkeypatch):
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: True)
    notify = AsyncMock()
    monkeypatch.setattr("notifications.openclaw_notifier.notify_ib_disconnect", notify)

    wd = _wd(monkeypatch, "01:00-01:30")
    wd.consecutive_failures = 5
    monkeypatch.setattr(wd, "_in_restart_window", lambda now_minutes=None: False)
    wd._maybe_alert()
    await asyncio.sleep(0)
    assert notify.call_count == 1


# --- reconnect-spacing tightening ------------------------------------------

@pytest.mark.asyncio
async def test_spacing_tightened_inside_window(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_INTERVAL", "10")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: False)
    dm = _DM(connected=False, reconnect_result=False)
    wd = _wd(monkeypatch, "01:00-01:30", dm=dm)
    monkeypatch.setattr(wd, "_in_restart_window", lambda now_minutes=None: True)
    clock = {"t": 1000.0}
    monkeypatch.setattr("services.ib_data_watchdog.time.monotonic", lambda: clock["t"])

    await wd._tick()  # failure #1 — tight backoff == interval (NOT 10*2**1)
    assert dm.reconnect_calls == 1
    assert wd._next_eligible == 1000.0 + 10.0

    # Clock NOT advanced: outside a window this would be gated; inside, the gate
    # is bypassed so we keep retrying.
    await wd._tick()
    assert dm.reconnect_calls == 2


@pytest.mark.asyncio
async def test_spacing_gated_outside_window(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_INTERVAL", "10")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: False)
    dm = _DM(connected=False, reconnect_result=False)
    wd = _wd(monkeypatch, None, dm=dm)  # no window
    clock = {"t": 1000.0}
    monkeypatch.setattr("services.ib_data_watchdog.time.monotonic", lambda: clock["t"])

    await wd._tick()  # failure #1 — exponential backoff 10*2**1 = 20
    assert dm.reconnect_calls == 1
    assert wd._next_eligible == 1000.0 + 20.0

    await wd._tick()  # clock unchanged → gated, no reconnect
    assert dm.reconnect_calls == 1
