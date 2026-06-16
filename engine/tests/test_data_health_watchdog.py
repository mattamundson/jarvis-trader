"""
JARVIS TRADER — Data-leg health watchdog tests.

Covers the mid-session IB *data* connection drop the execution-leg reconnect
(ib_gateway_connector) does not handle: detect disconnect during market hours,
attempt one bounded reconnect, and emit a throttled alert when the data leg is
down or its bars have gone stale while nominally connected.
"""

import pytest

from data.data_health_watchdog import DataHealthWatchdog


class FakeConn:
    """Stand-in for IBKRDataConnector (is_connected is a PROPERTY, connect is async)."""

    def __init__(self, connected, *, connect_result=None, raise_on_connect=False):
        self._connected = connected
        self._connect_result = connect_result
        self._raise = raise_on_connect
        self.connect_calls = 0

    @property
    def is_connected(self):
        return self._connected

    async def connect(self, retries=2, retry_backoff=2.0):
        self.connect_calls += 1
        if self._raise:
            raise RuntimeError("boom")
        if self._connect_result is not None:
            self._connected = self._connect_result
        return self._connected


class FakeMDM:
    def __init__(self, conn, last_ok=None):
        self.ibkr = conn
        self.ib_data_last_ok = last_ok


class AlertRec:
    def __init__(self):
        self.calls = []

    async def __call__(self, msg):
        self.calls.append(msg)


def _mk(mdm, alert, clock, **kw):
    kw.setdefault("reconnect_enabled", True)
    kw.setdefault("alert_cooldown", 900.0)
    kw.setdefault("staleness_limit", 600.0)
    kw.setdefault("check_interval", 1.0)
    kw.setdefault("is_market_hours_fn", lambda: True)
    return DataHealthWatchdog(mdm, alert_cb=alert, now_fn=lambda: clock["t"], **kw)


@pytest.mark.asyncio
async def test_connected_and_fresh_no_action():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=True)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn, last_ok=999.0), alert, clock)
    assert await wd.tick() is None
    assert alert.calls == []
    assert conn.connect_calls == 0


@pytest.mark.asyncio
async def test_outside_market_hours_skips():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock, is_market_hours_fn=lambda: False)
    assert await wd.tick() is None
    assert alert.calls == []
    assert conn.connect_calls == 0


@pytest.mark.asyncio
async def test_none_connector_skips():
    clock = {"t": 1000.0}
    alert = AlertRec()
    wd = _mk(FakeMDM(None), alert, clock)
    assert await wd.tick() is None
    assert alert.calls == []


@pytest.mark.asyncio
async def test_disconnect_reconnect_success_no_alert():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False, connect_result=True)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn, last_ok=1000.0), alert, clock)
    assert await wd.tick() is None
    assert conn.connect_calls == 1
    assert alert.calls == []


@pytest.mark.asyncio
async def test_disconnect_reconnect_fail_alerts():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False, connect_result=False)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock)
    reason = await wd.tick()
    assert conn.connect_calls == 1
    assert reason is not None and "DOWN" in reason
    assert len(alert.calls) == 1


@pytest.mark.asyncio
async def test_reconnect_disabled_alerts_without_connect():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock, reconnect_enabled=False)
    reason = await wd.tick()
    assert conn.connect_calls == 0
    assert reason is not None and "DOWN" in reason
    assert len(alert.calls) == 1


@pytest.mark.asyncio
async def test_connect_exception_handled_and_alerts():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False, raise_on_connect=True)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock)
    reason = await wd.tick()
    assert conn.connect_calls == 1
    assert reason is not None and "DOWN" in reason
    assert len(alert.calls) == 1


@pytest.mark.asyncio
async def test_alert_throttled_within_cooldown():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock, reconnect_enabled=False, alert_cooldown=900.0)
    assert await wd.tick() is not None
    clock["t"] = 1100.0  # 100s later, < cooldown
    assert await wd.tick() is None
    assert len(alert.calls) == 1


@pytest.mark.asyncio
async def test_alert_again_after_cooldown():
    clock = {"t": 1000.0}
    conn = FakeConn(connected=False)
    alert = AlertRec()
    wd = _mk(FakeMDM(conn), alert, clock, reconnect_enabled=False, alert_cooldown=900.0)
    assert await wd.tick() is not None
    clock["t"] = 1000.0 + 901.0  # past cooldown
    assert await wd.tick() is not None
    assert len(alert.calls) == 2


@pytest.mark.asyncio
async def test_staleness_alert_when_connected_but_stale():
    clock = {"t": 2000.0}
    conn = FakeConn(connected=True)
    alert = AlertRec()
    # last_ok 700s ago, staleness_limit 600s -> stale
    wd = _mk(FakeMDM(conn, last_ok=1300.0), alert, clock, staleness_limit=600.0)
    reason = await wd.tick()
    assert reason is not None and "stale" in reason.lower()
    assert conn.connect_calls == 0  # connected, no reconnect
    assert len(alert.calls) == 1
