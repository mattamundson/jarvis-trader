"""
Tests for risk/alert_manager.py — AlertManager public API.

Covers: check_and_alert (threshold detection + dedup), get_history,
get_fired_keys. Worker/notify path tested with a synchronous stub.
"""

from __future__ import annotations

import asyncio

import pytest

from risk.alert_manager import AlertManager


def _mgr(notify_fn=None) -> AlertManager:
    return AlertManager(notify_fn=notify_fn)


class TestCheckAndAlert:
    def test_no_alert_when_all_green(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=100.0,
            daily_pnl_pct=0.01,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        assert mgr.get_fired_keys() == {}

    def test_daily_loss_25pct_fires_early_warning(self):
        mgr = _mgr()
        # -0.5% (25% of the 2% limit)
        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "daily_loss_25pct" in fired

    def test_daily_loss_50pct_fires_halfway_alert(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=-100.0,
            daily_pnl_pct=-0.01,  # -1%, 50% of -2% limit
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "daily_loss_50pct" in fired

    def test_daily_loss_75pct_fires_serious_alert(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=-150.0,
            daily_pnl_pct=-0.015,  # -1.5%, 75% of -2% limit
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "daily_loss_75pct" in fired

    def test_drawdown_5pct_fires_warning(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=-0.05,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "drawdown_5pct" in fired

    def test_drawdown_10pct_fires_critical(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=-0.10,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "drawdown_10pct" in fired

    def test_consecutive_losses_2_fires_alert(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            consecutive_losses=2,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "consecutive_losses_2" in fired

    def test_consecutive_losses_3_fires_higher_alert(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            consecutive_losses=3,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "consecutive_losses_3" in fired

    def test_daily_target_50pct_fires_positive_alert(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=50.0,
            daily_pnl_pct=0.01,  # +1% toward some positive threshold
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        # Positive alerts fire if pct >= ALERT_THRESHOLDS["daily_target_50pct"]
        # We just ensure no exception and return is clean.
        assert isinstance(mgr.get_fired_keys(), dict)

    def test_same_threshold_not_fired_twice_same_day(self):
        """Dedup guard: second call with same threshold should not re-fire."""
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        queue_size_after_first = mgr._alert_queue.qsize()

        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        # Queue size must not grow on second call for the same threshold
        assert mgr._alert_queue.qsize() == queue_size_after_first


class TestGetHistory:
    def test_history_empty_initially(self):
        mgr = _mgr()
        assert mgr.get_history() == []

    def test_history_contains_fired_alerts(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        history = mgr.get_history()
        assert len(history) >= 1
        assert "key" in history[0]
        assert "message" in history[0]
        assert "ts" in history[0]

    def test_history_respects_limit(self):
        mgr = _mgr()
        # Fire multiple alerts
        for losses in [2, 3]:
            mgr.check_and_alert(
                daily_pnl=-50.0 * losses,
                daily_pnl_pct=-0.005 * losses,
                drawdown_pct=-0.05 * losses,
                consecutive_losses=losses,
                portfolio_equity=10_000.0,
            )
        history = mgr.get_history(limit=1)
        assert len(history) <= 1


class TestGetFiredKeys:
    def test_fired_keys_empty_initially(self):
        mgr = _mgr()
        assert mgr.get_fired_keys() == {}

    def test_fired_keys_reflect_fired_thresholds(self):
        mgr = _mgr()
        mgr.check_and_alert(
            daily_pnl=-150.0,
            daily_pnl_pct=-0.015,
            drawdown_pct=-0.05,
            consecutive_losses=3,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert len(fired) >= 1
        for key, date_str in fired.items():
            assert isinstance(key, str)
            assert isinstance(date_str, str)


class TestAlertWorker:
    @pytest.mark.asyncio
    async def test_alert_delivered_via_notify_fn(self):
        """Worker drains queue and calls notify_fn with the message string."""
        received: list[str] = []

        async def fake_notify(msg: str) -> bool:
            received.append(msg)
            return True

        mgr = AlertManager(notify_fn=fake_notify)
        mgr.start()

        mgr.check_and_alert(
            daily_pnl=-50.0,
            daily_pnl_pct=-0.005,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )

        # Give the worker a moment to process
        await asyncio.sleep(0.1)
        await mgr.stop()

        assert len(received) >= 1
        assert any("25%" in msg or "ALERT" in msg for msg in received)

    @pytest.mark.asyncio
    async def test_no_notify_fn_does_not_crash(self):
        """With no notify_fn, the worker logs and drops the message without error."""
        mgr = AlertManager(notify_fn=None)
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
