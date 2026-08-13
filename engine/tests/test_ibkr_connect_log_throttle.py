"""Tests for the P0.6 IBKR connect-failure log throttle (SOTA plan item).

Prior to this change, an extended IB Gateway outage logged a fresh WARNING on
every single ``connect()`` attempt for as long as the outage lasted —
including every ``IBDataWatchdog`` poll tick, each of which rebuilds a new
``IBKRDataConnector`` instance. These tests prove that repeated failures
within the exponential backoff window collapse to at most one real log line
plus periodic "still down, N suppressed" summaries — not raw per-attempt
spam — and that state is shared across instances (module-scoped, keyed by
host/port) and clears on a successful reconnect.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from data import market_data
from data.market_data import IBKRDataConnector

_LOGGER_NAME = "data.market_data"


def _mock_ib_factory(connect_side_effects):
    """Build an IB() factory whose connectAsync pops the next side effect:
    None -> success, Exception instance -> raise. Records each instance."""
    instances = []
    seq = list(connect_side_effects)

    def factory(*_a, **_k):
        ib = MagicMock()
        ib.disconnect = MagicMock()

        async def _connect(*_ca, **_ck):
            eff = seq.pop(0)
            if isinstance(eff, BaseException):
                raise eff
            return eff

        ib.connectAsync = _connect
        instances.append(ib)
        return ib

    return factory, instances


@pytest.fixture(autouse=True)
def _reset_throttle():
    """Throttle state is module-scoped by design (see market_data.py) so it
    survives connector-instance rebuilds — reset it around every test to
    keep tests isolated from each other."""
    market_data._reset_connect_fail_throttle()
    yield
    market_data._reset_connect_fail_throttle()


async def _fail_once(host: str, port: int, client_id: int, detail: str = "refused") -> bool:
    """Run one connect() call (single attempt) that fails with a fresh
    IBKRDataConnector instance, mirroring how IBDataWatchdog / reconnect_ibkr
    rebuild the connector on every reconnect attempt."""
    conn = IBKRDataConnector(host=host, port=port, client_id=client_id)
    factory, _ = _mock_ib_factory([ConnectionRefusedError(detail)])
    with patch("ib_async.IB", side_effect=factory):
        return await conn.connect(retries=0, retry_backoff=0)


@pytest.mark.asyncio
async def test_repeated_failures_collapse_to_one_real_log_line(caplog):
    """5 back-to-back connect() failures (fresh instance each time, as the
    watchdog does) within the backoff window must produce exactly ONE real
    WARNING, not 5 raw ConnectionRefused lines."""
    host, port, client_id = "127.0.0.1", 54321, 1

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        for _ in range(5):
            ok = await _fail_once(host, port, client_id)
            assert ok is False

    real_warnings = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(real_warnings) == 1, (
        f"expected exactly 1 real log line for 5 rapid failures, got "
        f"{len(real_warnings)}: {[r.getMessage() for r in real_warnings]}"
    )
    assert "refused" in real_warnings[0].getMessage()


@pytest.mark.asyncio
async def test_backoff_elapsed_emits_suppressed_summary(caplog, monkeypatch):
    """Once the exponential backoff window elapses, the NEXT failure logs a
    'still down, N suppressed' summary instead of the raw per-attempt
    detail — proving suppressed attempts aren't silently dropped forever."""
    host, port, client_id = "127.0.0.1", 54322, 1
    fake_now = [1000.0]
    monkeypatch.setattr(market_data.time, "monotonic", lambda: fake_now[0])

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        # First failure logs immediately (streak 1).
        await _fail_once(host, port, client_id)
        # 3 more failures inside the backoff window -- suppressed.
        for _ in range(3):
            await _fail_once(host, port, client_id)
        assert len(caplog.records) == 1

        # Advance the clock well past the backoff window and fail once more.
        fake_now[0] += 400.0
        await _fail_once(host, port, client_id)

    assert len(caplog.records) == 2
    summary = caplog.records[1].getMessage()
    assert "still down" in summary.lower()
    assert "suppressed" in summary.lower()
    assert "3 attempt" in summary  # the 3 suppressed since the last real log


@pytest.mark.asyncio
async def test_throttle_shared_across_fresh_connector_instances(caplog):
    """Production reconnects (IBDataWatchdog / reconnect_ibkr) build a brand
    new IBKRDataConnector every attempt. The throttle must key on
    (host, port), not instance identity, or it would never actually
    suppress anything in production."""
    host, port, client_id = "127.0.0.1", 54324, 1

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        conn_a = IBKRDataConnector(host=host, port=port, client_id=client_id)
        conn_b = IBKRDataConnector(host=host, port=port, client_id=client_id)
        assert conn_a is not conn_b

        factory_a, _ = _mock_ib_factory([ConnectionRefusedError("a")])
        with patch("ib_async.IB", side_effect=factory_a):
            await conn_a.connect(retries=0, retry_backoff=0)

        factory_b, _ = _mock_ib_factory([ConnectionRefusedError("b")])
        with patch("ib_async.IB", side_effect=factory_b):
            await conn_b.connect(retries=0, retry_backoff=0)

    real_warnings = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(real_warnings) == 1


@pytest.mark.asyncio
async def test_successful_connect_resets_throttle_and_logs_recovery(caplog):
    """A successful connect() after failures must clear the throttle state
    and note the recovery, so the NEXT failure logs immediately again
    instead of staying suppressed forever."""
    host, port, client_id = "127.0.0.1", 54323, 1

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await _fail_once(host, port, client_id)
    assert len([r for r in caplog.records if r.name == _LOGGER_NAME]) == 1

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        conn2 = IBKRDataConnector(host=host, port=port, client_id=client_id)
        factory2, _ = _mock_ib_factory([None])
        with patch("ib_async.IB", side_effect=factory2):
            ok = await conn2.connect(retries=0, retry_backoff=0)
        assert ok is True

    recovery_lines = [
        r for r in caplog.records if r.name == _LOGGER_NAME and "recovered" in r.getMessage().lower()
    ]
    assert len(recovery_lines) == 1

    # State is cleared -- the next failure must log immediately again (fresh
    # streak of 1), not remain suppressed from before the recovery.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        ok = await _fail_once(host, port, client_id, detail="refused again")
        assert ok is False

    real_warnings = [r for r in caplog.records if r.name == _LOGGER_NAME]
    assert len(real_warnings) == 1
    assert "refused again" in real_warnings[0].getMessage()


def test_reset_connect_fail_throttle_clears_single_target():
    """The test/ops reset hook can target one (host, port) without wiping
    unrelated targets' state."""
    market_data._connect_fail_state[("127.0.0.1", 1)] = {
        "streak": 3,
        "last_log": 10.0,
        "suppressed": 2,
    }
    market_data._connect_fail_state[("127.0.0.1", 2)] = {
        "streak": 1,
        "last_log": 5.0,
        "suppressed": 0,
    }

    market_data._reset_connect_fail_throttle("127.0.0.1", 1)

    assert ("127.0.0.1", 1) not in market_data._connect_fail_state
    assert ("127.0.0.1", 2) in market_data._connect_fail_state

    market_data._reset_connect_fail_throttle()
    assert market_data._connect_fail_state == {}
