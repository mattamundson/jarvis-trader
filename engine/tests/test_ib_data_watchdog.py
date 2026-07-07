"""Offline tests for the IB data-leg auto-reconnect watchdog + honest detection.

Covers:
  - IBKRDataConnector.is_connected now consults the live socket; _on_disconnected flips it
  - MarketDataManager.reconnect_ibkr is idempotent and lock-guarded (builds once)
  - IBDataWatchdog: no-op when healthy, reconnect on drop, capped backoff + gating,
    reset on recovery, stale-data soft-drop (market-hours gated), disable flag, clean cancel
"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from data.market_data import IBKRDataConnector
from services.ib_data_watchdog import IBDataWatchdog

# --- honest is_connected detection -----------------------------------------

def test_is_connected_consults_live_socket():
    conn = IBKRDataConnector(client_id=9)
    conn._connected = True
    conn._ib = MagicMock()
    conn._ib.isConnected.return_value = False
    assert conn.is_connected is False          # live socket says no, despite flag

    conn._ib.isConnected.return_value = True
    assert conn.is_connected is True


def test_on_disconnected_marks_offline():
    conn = IBKRDataConnector(client_id=9)
    conn._connected = True
    conn._ib = MagicMock()
    conn._ib.isConnected.return_value = True
    conn._on_disconnected()
    assert conn._connected is False
    assert conn.is_connected is False


def test_is_connected_false_when_no_ib():
    conn = IBKRDataConnector(client_id=9)
    conn._connected = True
    conn._ib = None
    assert conn.is_connected is False


# --- reconnect_ibkr lock ----------------------------------------------------

@pytest.mark.asyncio
async def test_reconnect_ibkr_builds_once_under_concurrency(monkeypatch):
    from data import market_data as md

    class _FakeConn:
        count = 0

        def __init__(self, **kw):
            type(self).count += 1
            self._connected = False

        @property
        def is_connected(self):
            return self._connected

        async def connect(self):
            await asyncio.sleep(0.05)            # widen the race window
            self._connected = True
            return True

        async def disconnect(self):
            self._connected = False

        async def resubscribe_all(self):
            pass

    monkeypatch.setattr(md, "IBKRDataConnector", _FakeConn)
    monkeypatch.setattr(md, "RedditSentimentConnector", lambda *a, **k: MagicMock())
    cfg = SimpleNamespace(
        IBKR_HOST="127.0.0.1", IBKR_PORT=4002, IBKR_CLIENT_ID=200,
        IBKR_CONNECT_TIMEOUT_SECONDS=5.0,
    )
    mgr = md.MarketDataManager(cfg)
    mgr.ibkr = None

    results = await asyncio.gather(mgr.reconnect_ibkr(), mgr.reconnect_ibkr())
    assert all(results)
    assert _FakeConn.count == 1                  # lock prevented a duplicate rebuild


# --- watchdog tick behavior -------------------------------------------------

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
async def test_tick_noop_when_connected(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    dm = _DM(connected=True)
    wd = IBDataWatchdog(dm)
    await wd._tick()
    assert dm.reconnect_calls == 0


@pytest.mark.asyncio
async def test_tick_reconnects_on_drop(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    dm = _DM(connected=False, reconnect_result=True)
    wd = IBDataWatchdog(dm)
    await wd._tick()
    assert dm.reconnect_calls == 1
    assert wd.consecutive_failures == 0
    assert wd.last_success_ts is not None


@pytest.mark.asyncio
async def test_backoff_grows_caps_and_gates(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_INTERVAL", "10")
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_MAX_BACKOFF", "300")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: False)  # suppress alert
    dm = _DM(connected=False, reconnect_result=False)
    wd = IBDataWatchdog(dm)
    clock = {"t": 1000.0}
    monkeypatch.setattr("services.ib_data_watchdog.time.monotonic", lambda: clock["t"])

    await wd._tick()                              # failure #1
    assert dm.reconnect_calls == 1 and wd.consecutive_failures == 1
    assert wd._next_eligible == 1000.0 + 20.0     # 10 * 2**1

    await wd._tick()                              # gated — monotonic unchanged
    assert dm.reconnect_calls == 1

    clock["t"] = wd._next_eligible + 0.1          # past the gate
    await wd._tick()                              # failure #2
    assert dm.reconnect_calls == 2 and wd.consecutive_failures == 2

    for _ in range(12):                           # drive failures up to test the cap
        clock["t"] = wd._next_eligible + 0.1
        await wd._tick()
    assert (wd._next_eligible - clock["t"]) <= 300.0 + 0.2


@pytest.mark.asyncio
async def test_counters_reset_on_recovery(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: False)
    dm = _DM(connected=False, reconnect_result=False)
    wd = IBDataWatchdog(dm)
    clock = {"t": 0.0}
    monkeypatch.setattr("services.ib_data_watchdog.time.monotonic", lambda: clock["t"])

    await wd._tick()                              # fail 1
    clock["t"] = wd._next_eligible + 1
    await wd._tick()                              # fail 2
    assert wd.consecutive_failures == 2

    dm._reconnect_result = True                   # gateway comes back
    clock["t"] = wd._next_eligible + 1
    await wd._tick()
    assert wd.consecutive_failures == 0
    assert wd._next_eligible == 0.0


@pytest.mark.asyncio
async def test_stale_data_reconnects_during_market_hours(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "60")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: True)
    dm = _DM(connected=True, reconnect_result=True, last_ts=time.time() - 3600)
    wd = IBDataWatchdog(dm)
    await wd._tick()
    assert dm.reconnect_calls == 1                # connected but stale -> reconnect


@pytest.mark.asyncio
async def test_stale_data_ignored_outside_market_hours(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "60")
    monkeypatch.setattr("health.ib_monitor.is_market_hours", lambda: False)
    dm = _DM(connected=True, last_ts=time.time() - 3600)
    wd = IBDataWatchdog(dm)
    await wd._tick()
    assert dm.reconnect_calls == 0


@pytest.mark.asyncio
async def test_disabled_via_env_starts_no_task(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_ENABLED", "0")
    dm = _DM(connected=False)
    wd = IBDataWatchdog(dm)
    assert wd.enabled is False
    await wd.start()
    assert wd._task is None
    assert dm._watchdog is wd                     # still registered for /health
    await wd.stop()


@pytest.mark.asyncio
async def test_clean_cancel_on_shutdown(monkeypatch):
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_ENABLED", "1")
    monkeypatch.setenv("IBKR_DATA_WATCHDOG_INTERVAL", "5")
    monkeypatch.setenv("IBKR_DATA_STALE_SECONDS", "0")
    dm = _DM(connected=True)
    wd = IBDataWatchdog(dm)
    await wd.start()
    assert wd._task is not None
    await asyncio.sleep(0)                         # let the loop reach its first sleep
    await wd.stop()
    assert wd._running is False
    assert wd._task is None
