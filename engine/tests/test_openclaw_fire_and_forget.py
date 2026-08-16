"""
Regression tests for openclaw_notifier's fire-and-forget Discord dispatch.

Prior to this change, all 10 `asyncio.ensure_future(...)` call sites in
`notifications/openclaw_notifier.py` fired the wrapped Discord coroutine with
no error handler attached. If that coroutine raised, the exception became an
unretrieved asyncio Task exception -- invisible to the caller, surfaced (if at
all) only via Python's default GC-time "Task exception was never retrieved"
log line, which nothing in this codebase reads. Since REQUIRE_HUMAN_APPROVAL=
False, these alerts are the only human-visible record of an autonomous paper
trade, so a silently-failed alert meant zero durable record that oversight
failed.

Covered:
  1. `_track_fire_and_forget` itself -- a raising coroutine now produces a
     loud ERROR log (with exc_info) instead of a silent unretrieved-task
     exception; a successful coroutine logs nothing at ERROR.
  2. The `record_failure` opt-in -- only wired for notify_trade_opened /
     notify_trade_closed -- writes a `status="failed"` row to the existing
     `alert_log` table on Discord exception or a plain `False` return; call
     sites that don't opt in never touch the DB.
  3. End-to-end: notify_trade_opened / notify_trade_closed actually invoke
     the alert_log durable trace (via database.schema.get_db) on both a
     WhatsApp send failure and a Discord coroutine exception.
  4. Existing behavior is unchanged: WhatsApp is still awaited and its
     result is still what the function returns, regardless of whether the
     fire-and-forget Discord dispatch succeeds, fails, or raises; dispatch is
     still non-blocking (the caller does not wait on the Discord coroutine).
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

os.environ["TESTING"] = ""  # these tests exercise the real send path, not TESTING mode
os.environ.setdefault("OPENCLAW_WHATSAPP_TO", "+15555550000")
os.environ["OPENCLAW_ENABLED"] = "true"

from notifications import openclaw_notifier as on  # noqa: E402

_LOGGER_NAME = "notifications.openclaw_notifier"


async def _drain() -> None:
    """Yield control back to the event loop enough times for a
    fire-and-forget task (and its add_done_callback) to actually run."""
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _reset_notifier_state():
    """Fire-and-forget dispatch is orthogonal to the per-symbol cooldown /
    Globex-hours gates -- neutralize them so these tests exercise the
    dispatch path deterministically regardless of wall-clock time."""
    on._last_sent.clear()
    with patch.object(on, "_is_globex_open", return_value=True):
        yield
    on._last_sent.clear()


# ---------------------------------------------------------------------------
# 1. _track_fire_and_forget unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raising_coroutine_logs_loud_error(caplog):
    async def _boom():
        raise ValueError("discord webhook exploded")

    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        task = on._track_fire_and_forget(_boom(), label="unit_test_boom")
        await _drain()

    assert task.done()
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "unit_test_boom" in error_records[0].getMessage()
    # Loud means exc_info is attached, not just a bare message.
    assert error_records[0].exc_info is not None
    assert error_records[0].exc_info[0] is ValueError


@pytest.mark.asyncio
async def test_raising_coroutine_does_not_propagate_to_caller():
    """The whole point of fire-and-forget is that a raise inside the
    tracked coroutine must not blow up the caller."""
    async def _boom():
        raise RuntimeError("should not propagate")

    task = on._track_fire_and_forget(_boom(), label="no_propagate")
    await _drain()  # must not raise
    assert task.done()


@pytest.mark.asyncio
async def test_successful_coroutine_logs_no_error(caplog):
    async def _ok():
        return True

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        task = on._track_fire_and_forget(_ok(), label="unit_test_ok")
        await _drain()

    assert task.done()
    assert task.result() is True
    assert not [r for r in caplog.records if r.levelno == logging.ERROR]


@pytest.mark.asyncio
async def test_cancelled_task_is_not_treated_as_a_failure():
    """task.exception() raises CancelledError on a cancelled task -- the
    callback must guard against that, and must not record a failure."""
    async def _slow():
        await asyncio.sleep(10)

    with patch.object(on, "_record_alert_failure") as mock_record:
        task = on._track_fire_and_forget(
            _slow(),
            label="cancelled",
            record_failure={
                "alert_type": "trade_opened",
                "channel": "discord",
                "message": "m",
                "symbol": "MES",
            },
        )
        task.cancel()
        await _drain()

    assert task.cancelled()
    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_no_record_failure_kwarg_never_touches_alert_log():
    """The 8 call sites that don't pass record_failure must stay
    loud-log-only -- no DB write attempted on exception."""
    async def _boom():
        raise RuntimeError("boom")

    with patch.object(on, "_record_alert_failure") as mock_record:
        task = on._track_fire_and_forget(_boom(), label="no_record_failure")
        await _drain()

    assert task.done()
    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_exception_with_record_failure_calls_record_alert_failure():
    async def _boom():
        raise RuntimeError("webhook down")

    with patch.object(on, "_record_alert_failure") as mock_record:
        task = on._track_fire_and_forget(
            _boom(),
            label="with_record_failure",
            record_failure={
                "alert_type": "trade_opened",
                "channel": "discord",
                "message": "m",
                "symbol": "MES",
            },
        )
        await _drain()

    assert task.done()
    mock_record.assert_called_once()
    _, kwargs = mock_record.call_args
    assert kwargs["alert_type"] == "trade_opened"
    assert kwargs["channel"] == "discord"
    assert "RuntimeError" in kwargs["error"]


@pytest.mark.asyncio
async def test_false_result_with_record_failure_calls_record_alert_failure():
    """A clean `return False` (no exception) from the wrapped coroutine is
    still a failed send and must also be recorded when opted in."""
    async def _fail():
        return False

    with patch.object(on, "_record_alert_failure") as mock_record:
        task = on._track_fire_and_forget(
            _fail(),
            label="false_result",
            record_failure={
                "alert_type": "trade_closed",
                "channel": "discord",
                "message": "m",
                "symbol": "MES",
            },
        )
        await _drain()

    assert task.done()
    mock_record.assert_called_once()


@pytest.mark.asyncio
async def test_true_result_with_record_failure_does_not_record():
    async def _ok():
        return True

    with patch.object(on, "_record_alert_failure") as mock_record:
        task = on._track_fire_and_forget(
            _ok(),
            label="true_result",
            record_failure={
                "alert_type": "trade_closed",
                "channel": "discord",
                "message": "m",
                "symbol": "MES",
            },
        )
        await _drain()

    assert task.done()
    mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# 2. notify_trade_opened / notify_trade_closed durable-trace wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trade_opened_whatsapp_failure_writes_alert_log():
    fake_db = MagicMock()
    with patch.object(on, "_send", new=AsyncMock(return_value=False)), \
         patch.object(on._discord, "discord_trade_opened", new=AsyncMock(return_value=True)), \
         patch("database.schema.get_db", return_value=fake_db):
        result = await on.notify_trade_opened(
            symbol="MES", action="BUY", quantity=1, entry_price=5000.0
        )
        await _drain()

    assert result is False
    fake_db.insert_alert_log.assert_any_call(
        alert_type="trade_opened",
        message=ANY,
        channel="whatsapp",
        symbol="MES",
        status="failed",
        error="OpenClaw WhatsApp send returned False (see logs)",
    )


@pytest.mark.asyncio
async def test_trade_opened_discord_exception_writes_alert_log(caplog):
    fake_db = MagicMock()

    async def _boom(**kwargs):
        raise RuntimeError("discord down")

    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME), \
         patch.object(on, "_send", new=AsyncMock(return_value=True)), \
         patch.object(on._discord, "discord_trade_opened", new=_boom), \
         patch("database.schema.get_db", return_value=fake_db):
        result = await on.notify_trade_opened(
            symbol="MES", action="BUY", quantity=1, entry_price=5000.0
        )
        await _drain()

    # WhatsApp succeeded -- the return value is unaffected by the Discord failure.
    assert result is True
    assert fake_db.insert_alert_log.called
    _, kwargs = fake_db.insert_alert_log.call_args
    assert kwargs["alert_type"] == "trade_opened"
    assert kwargs["channel"] == "discord"
    assert kwargs["status"] == "failed"
    assert kwargs["symbol"] == "MES"
    assert "RuntimeError" in kwargs["error"]
    # And it was also logged loudly (item 1's guarantee still holds here).
    assert any(r.levelno == logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_trade_closed_whatsapp_failure_writes_alert_log():
    fake_db = MagicMock()
    with patch.object(on, "_send", new=AsyncMock(return_value=False)), \
         patch.object(on._discord, "discord_trade_closed", new=AsyncMock(return_value=True)), \
         patch("database.schema.get_db", return_value=fake_db):
        result = await on.notify_trade_closed(
            symbol="MES", action="BUY", entry_price=5000.0, exit_price=5010.0, pnl=50.0
        )
        await _drain()

    assert result is False
    fake_db.insert_alert_log.assert_any_call(
        alert_type="trade_closed",
        message=ANY,
        channel="whatsapp",
        symbol="MES",
        status="failed",
        error="OpenClaw WhatsApp send returned False (see logs)",
    )


@pytest.mark.asyncio
async def test_record_alert_failure_missing_db_is_non_fatal():
    """If get_db() raises (DB not initialized yet), _record_alert_failure
    must swallow it -- never blow up the fire-and-forget callback."""
    with patch("database.schema.get_db", side_effect=RuntimeError("not initialized")):
        on._record_alert_failure(
            alert_type="trade_opened", channel="whatsapp", message="m", symbol="MES", error="x"
        )  # must not raise


@pytest.mark.asyncio
async def test_successful_trade_opened_does_not_write_alert_log():
    fake_db = MagicMock()
    with patch.object(on, "_send", new=AsyncMock(return_value=True)), \
         patch.object(on._discord, "discord_trade_opened", new=AsyncMock(return_value=True)), \
         patch("database.schema.get_db", return_value=fake_db):
        result = await on.notify_trade_opened(
            symbol="MES", action="BUY", quantity=1, entry_price=5000.0
        )
        await _drain()

    assert result is True
    fake_db.insert_alert_log.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Existing behavior unchanged: WhatsApp result still drives the return
#    value; dispatch is still fire-and-forget / non-blocking.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_signal_returns_whatsapp_result_even_when_discord_raises():
    async def _boom(**kwargs):
        raise RuntimeError("discord webhook down")

    with patch.object(on, "_send", new=AsyncMock(return_value=True)), \
         patch.object(on._discord, "discord_signal", new=_boom):
        result = await on.notify_signal(symbol="MES", action="BUY", confidence=0.9)
        await _drain()

    assert result is True


@pytest.mark.asyncio
async def test_notify_signal_returns_false_on_whatsapp_failure_regardless_of_discord():
    with patch.object(on, "_send", new=AsyncMock(return_value=False)), \
         patch.object(on._discord, "discord_signal", new=AsyncMock(return_value=True)):
        result = await on.notify_signal(symbol="MGC", action="SELL", confidence=0.8)
        await _drain()

    assert result is False


@pytest.mark.asyncio
async def test_dispatch_is_non_blocking():
    """notify_kill_switch must return as soon as WhatsApp finishes, without
    waiting on the (slow) Discord coroutine."""
    discord_started = asyncio.Event()
    discord_finished = asyncio.Event()

    async def _slow_discord(**kwargs):
        discord_started.set()
        await asyncio.sleep(0.2)
        discord_finished.set()
        return True

    with patch.object(on, "_send", new=AsyncMock(return_value=True)), \
         patch.object(on._discord, "discord_kill_switch", new=_slow_discord):
        result = await on.notify_kill_switch(reason="daily_loss_limit", message="-8.1%")

    assert result is True
    # notify_kill_switch already returned -- the slow Discord coroutine must
    # not have finished yet (it may or may not have started).
    assert not discord_finished.is_set()
    await asyncio.wait_for(discord_finished.wait(), timeout=2)


@pytest.mark.asyncio
async def test_notify_regime_change_uses_tracked_dispatch_not_raw_ensure_future():
    """Sanity check that the call site actually goes through the helper
    (i.e. the raw `asyncio.ensure_future` call site was really replaced)."""
    with patch.object(on, "_send", new=AsyncMock(return_value=True)), \
         patch.object(on, "_track_fire_and_forget", wraps=on._track_fire_and_forget) as mock_track, \
         patch.object(on._discord, "discord_regime_change", new=AsyncMock(return_value=True)):
        result = await on.notify_regime_change("MES", "trend", "chop")
        await _drain()

    assert result is True
    mock_track.assert_called_once()
    _, kwargs = mock_track.call_args
    assert "discord_regime_change" in kwargs["label"]
    assert "MES" in kwargs["label"]
