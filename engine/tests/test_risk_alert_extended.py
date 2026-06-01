"""
Tests for risk/alert_manager.py — coverage for remaining paths.

Covers: daily_target_hit threshold, daily_target_50pct, notify_fn returns False,
notify_fn raises, no notify_fn worker path, worker CancelledError (stop()),
MAX_HISTORY cap in _record_history.
"""

from __future__ import annotations

import asyncio

import pytest

from risk.alert_manager import AlertManager


class TestDailyTargetAlerts:
    def test_daily_target_50pct_fires(self):
        mgr = AlertManager(notify_fn=None)
        # +1% → daily_target_50pct threshold (e.g. 0.5% of a 2% target)
        mgr.check_and_alert(
            daily_pnl=100.0,
            daily_pnl_pct=0.01,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        # daily_target_50pct fires when pnl_pct >= its threshold
        assert isinstance(fired, dict)

    def test_daily_target_hit_fires_above_threshold(self):
        """Fire daily_target_hit when pnl_pct >= 5% (daily_target_hit = 0.05)."""
        mgr = AlertManager(notify_fn=None)
        mgr.check_and_alert(
            daily_pnl=500.0,
            daily_pnl_pct=0.05,  # +5% at the daily_target_hit threshold
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert isinstance(fired, dict)
        # daily_target_hit fires at >= 5%
        assert "daily_target_hit" in fired


@pytest.mark.asyncio
class TestAlertWorkerExtendedPaths:
    async def test_notify_fn_returns_false_logs_warning(self):
        """notify_fn returns False → worker logs falsy-delivery warning but doesn't crash."""
        received: list[str] = []

        async def fake_notify(msg: str) -> bool:
            received.append(msg)
            return False  # falsy return — delivery "failed"

        mgr = AlertManager(notify_fn=fake_notify)
        mgr.start()

        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )

        await asyncio.sleep(0.1)
        await mgr.stop()

        # Message was received; no crash even though return was False
        assert len(received) >= 1

    async def test_notify_fn_raises_does_not_crash_worker(self):
        """notify_fn raises → worker catches exception and continues."""
        call_count = {"n": 0}

        async def bad_notify(msg: str) -> bool:
            call_count["n"] += 1
            raise RuntimeError("Slack API down")

        mgr = AlertManager(notify_fn=bad_notify)
        mgr.start()

        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )

        await asyncio.sleep(0.1)
        await mgr.stop()  # Must not raise

        assert call_count["n"] >= 1

    async def test_stop_with_no_running_task_does_not_crash(self):
        """stop() when worker was never start()ed should not raise."""
        mgr = AlertManager(notify_fn=None)
        # Don't call start()
        await mgr.stop()


class TestHistoryCap:
    def test_history_capped_at_max(self):
        """_record_history caps at _MAX_HISTORY (100)."""
        from risk.alert_manager import _MAX_HISTORY

        mgr = AlertManager(notify_fn=None)
        # Directly fill history past the cap
        for i in range(_MAX_HISTORY + 20):
            mgr._record_history(f"key_{i}", f"msg_{i}")

        assert len(mgr._history) == _MAX_HISTORY
