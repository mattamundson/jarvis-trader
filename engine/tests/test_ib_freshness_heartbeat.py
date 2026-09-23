"""Offline tests for the IB market-data freshness heartbeat.

Covers:
  - MarketDataManager._record_ibkr_freshness stamps the in-process timestamp AND
    writes a timezone-aware UTC ISO value to datasource:ib_gateway:last_update,
    and never raises if Redis is down (best-effort hot path).
  - IBFreshnessHeartbeat._beat: stamps on a real IB price (market-hours gated),
    no-op when disconnected / outside market hours / no price / snapshot error,
    and disable flag suppresses the loop.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.ib_freshness_heartbeat import IBFreshnessHeartbeat

# --- MarketDataManager._record_ibkr_freshness ------------------------------

def test_record_ibkr_freshness_writes_aware_utc_heartbeat(monkeypatch):
    from data import market_data as md

    captured = {}

    class _FakeRedis:
        def __init__(self, **kw):
            captured["ctor_kw"] = kw

        def set(self, key, val):
            captured["key"] = key
            captured["val"] = val

    monkeypatch.setattr(md, "redis", SimpleNamespace(Redis=_FakeRedis), raising=False)
    # The helper does a local `import redis`; ensure that name resolves to our fake.
    import sys
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=_FakeRedis))

    ns = SimpleNamespace(_last_ibkr_data_ts=None)
    md.MarketDataManager._record_ibkr_freshness(ns)

    assert ns._last_ibkr_data_ts is not None            # in-process ts stamped
    assert captured["key"] == "datasource:ib_gateway:last_update"
    # Value must be timezone-AWARE ISO (data-integrity subtracts from aware now()).
    parsed = datetime.fromisoformat(captured["val"])
    assert parsed.tzinfo is not None


def test_record_ibkr_freshness_survives_redis_down(monkeypatch):
    import sys

    from data import market_data as md

    class _BoomRedis:
        def __init__(self, **kw):
            raise ConnectionError("redis down")

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=_BoomRedis))

    ns = SimpleNamespace(_last_ibkr_data_ts=None)
    md.MarketDataManager._record_ibkr_freshness(ns)          # must not raise
    assert ns._last_ibkr_data_ts is not None                 # ts still stamped


# --- IBFreshnessHeartbeat._beat --------------------------------------------

def _dm(*, connected=True, price=7500.0):
    async def _snap(symbol, is_futures):
        return {"last_price": price} if price is not None else {"last_price": None}

    stamped = {"n": 0}

    def _record():
        stamped["n"] += 1

    ibkr = SimpleNamespace(is_connected=connected, get_snapshot_price=_snap)
    dm = SimpleNamespace(ibkr=ibkr, _record_ibkr_freshness=_record,
                         _last_ibkr_data_ts=None)
    return dm, stamped


def _force_market_hours(monkeypatch, is_open: bool):
    import health.ib_monitor as ibm
    monkeypatch.setattr(ibm, "is_market_hours", lambda: is_open)


@pytest.mark.asyncio
async def test_beat_stamps_on_real_price(monkeypatch):
    _force_market_hours(monkeypatch, True)
    dm, stamped = _dm(price=7500.0)
    hb = IBFreshnessHeartbeat(dm)
    await hb._beat()
    assert stamped["n"] == 1
    assert hb.last_beat_ts is not None


@pytest.mark.asyncio
async def test_beat_noop_when_disconnected(monkeypatch):
    _force_market_hours(monkeypatch, True)
    dm, stamped = _dm(connected=False)
    hb = IBFreshnessHeartbeat(dm)
    await hb._beat()
    assert stamped["n"] == 0
    assert hb.last_beat_ts is None


@pytest.mark.asyncio
async def test_beat_noop_outside_market_hours(monkeypatch):
    _force_market_hours(monkeypatch, False)
    dm, stamped = _dm()
    hb = IBFreshnessHeartbeat(dm)
    await hb._beat()
    assert stamped["n"] == 0


@pytest.mark.asyncio
async def test_beat_noop_when_no_price(monkeypatch):
    _force_market_hours(monkeypatch, True)
    dm, stamped = _dm(price=None)
    hb = IBFreshnessHeartbeat(dm)
    await hb._beat()
    assert stamped["n"] == 0                 # socket-up-but-data-dead: honest, no stamp
    assert hb.last_beat_ts is None


@pytest.mark.asyncio
async def test_beat_swallows_snapshot_error(monkeypatch):
    _force_market_hours(monkeypatch, True)

    async def _boom(symbol, is_futures):
        raise TimeoutError("ib slow")

    ibkr = SimpleNamespace(is_connected=True, get_snapshot_price=_boom)
    stamped = {"n": 0}
    dm = SimpleNamespace(ibkr=ibkr,
                         _record_ibkr_freshness=lambda: stamped.__setitem__("n", stamped["n"] + 1),
                         _last_ibkr_data_ts=None)
    hb = IBFreshnessHeartbeat(dm)
    await hb._beat()                         # must not raise
    assert stamped["n"] == 0


@pytest.mark.asyncio
<<<<<<< HEAD
=======
async def test_repeated_probe_failure_is_audible_not_buried(monkeypatch, caplog):
    """2026-08-15 incident: this was the ONE component honestly detecting a
    wedged Gateway, and it logged the reason at DEBUG -- invisible at the
    default log level. The first failure and every 5th thereafter must reach
    WARNING; the in-between ones may stay at DEBUG so an extended outage
    doesn't flood the log every heartbeat interval."""
    _force_market_hours(monkeypatch, True)

    async def _boom(symbol, is_futures):
        raise TimeoutError("ib slow")

    ibkr = SimpleNamespace(is_connected=True, get_snapshot_price=_boom)
    dm = SimpleNamespace(ibkr=ibkr, _record_ibkr_freshness=lambda: None,
                         _last_ibkr_data_ts=None)
    hb = IBFreshnessHeartbeat(dm)

    import logging

    with caplog.at_level(logging.WARNING, logger="services.ib_freshness_heartbeat"):
        for _ in range(6):
            await hb._beat()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Failure 1 and failure 5 are audible; 2-4 and 6 are not (still DEBUG).
    assert len(warnings) == 2
    assert "1 consecutive" in warnings[0].message
    assert "5 consecutive" in warnings[1].message
    assert hb._consecutive_probe_failures == 6


@pytest.mark.asyncio
async def test_probe_failure_counter_resets_on_recovery(monkeypatch):
    """A recovered probe must reset the streak, so a later isolated blip
    doesn't inherit a stale count and mis-report as '(6 consecutive)'."""
    _force_market_hours(monkeypatch, True)

    calls = {"n": 0}

    async def _flaky(symbol, is_futures):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TimeoutError("ib slow")
        return {"last_price": 7500.0}

    ibkr = SimpleNamespace(is_connected=True, get_snapshot_price=_flaky)
    dm = SimpleNamespace(ibkr=ibkr, _record_ibkr_freshness=lambda: None,
                         _last_ibkr_data_ts=None)
    hb = IBFreshnessHeartbeat(dm)

    await hb._beat()  # fail 1
    await hb._beat()  # fail 2
    await hb._beat()  # recovers
    assert hb._consecutive_probe_failures == 0


@pytest.mark.asyncio
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
async def test_disabled_flag_suppresses_start(monkeypatch):
    monkeypatch.setenv("IBKR_HEARTBEAT_ENABLED", "0")
    dm, _ = _dm()
    hb = IBFreshnessHeartbeat(dm)
    assert hb.enabled is False
    await hb.start()
    assert hb._running is False
    assert hb._task is None
