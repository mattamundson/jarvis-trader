"""
Unit tests for engine/scripts/liveness_watchdog.py

Tests cover the state-change/debounce logic using a fake health-poller.
No network calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap engine path so the module is importable from the test runner
_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

import pytest

from scripts.liveness_watchdog import WatchdogState, evaluate

# ── Helpers ───────────────────────────────────────────────────────────────────


def _ok(**kwargs) -> dict:
    """Build a baseline healthy health snapshot."""
    base = {
        "status": "ok",
        "ibkr_data_connected": True,
        "kill_switch_active": False,
    }
    base.update(kwargs)
    return base


# ── Engine-down / miss threshold ──────────────────────────────────────────────


class TestEngineDown:
    def test_single_miss_no_alert(self):
        """One miss below threshold — no alert."""
        state = WatchdogState()
        alerts = evaluate(None, state, miss_threshold=3)
        assert alerts == []
        assert state.consecutive_misses == 1
        assert not state.engine_down

    def test_misses_below_threshold_no_alert(self):
        """Two misses with threshold=3 — still no alert."""
        state = WatchdogState()
        evaluate(None, state, miss_threshold=3)
        alerts = evaluate(None, state, miss_threshold=3)
        assert alerts == []
        assert state.consecutive_misses == 2

    def test_threshold_hit_fires_down_alert(self):
        """Exactly at threshold — DOWN alert fires."""
        state = WatchdogState()
        for _ in range(2):
            evaluate(None, state, miss_threshold=3)
        alerts = evaluate(None, state, miss_threshold=3)
        assert len(alerts) == 1
        assert "Engine DOWN" in alerts[0]
        assert state.engine_down is True

    def test_down_alert_fires_only_once(self):
        """Once engine_down=True, further misses produce no new alert."""
        state = WatchdogState()
        for _ in range(3):
            evaluate(None, state, miss_threshold=3)
        # Already down; more misses → no additional alerts
        alerts = evaluate(None, state, miss_threshold=3)
        assert alerts == []

    def test_threshold_1_fires_on_first_miss(self):
        """threshold=1 fires on the very first miss."""
        state = WatchdogState()
        alerts = evaluate(None, state, miss_threshold=1)
        assert len(alerts) == 1
        assert "Engine DOWN" in alerts[0]

    def test_miss_counter_increments_correctly(self):
        state = WatchdogState()
        for i in range(1, 4):
            evaluate(None, state, miss_threshold=10)
            assert state.consecutive_misses == i


# ── Recovery ──────────────────────────────────────────────────────────────────


class TestRecovery:
    def test_recovery_alert_after_down(self):
        """Engine comes back up after being marked down — RECOVERY fires."""
        state = WatchdogState()
        for _ in range(3):
            evaluate(None, state, miss_threshold=3)
        assert state.engine_down is True

        alerts = evaluate(_ok(), state, miss_threshold=3)
        assert any("RECOVERED" in a for a in alerts)
        assert state.engine_down is False
        assert state.consecutive_misses == 0

    def test_no_recovery_alert_if_never_down(self):
        """Healthy poll after healthy poll — no recovery alert."""
        state = WatchdogState()
        alerts = evaluate(_ok(), state, miss_threshold=3)
        assert not any("RECOVERED" in a for a in alerts)

    def test_miss_counter_resets_on_success(self):
        state = WatchdogState()
        evaluate(None, state, miss_threshold=5)
        evaluate(None, state, miss_threshold=5)
        evaluate(_ok(), state, miss_threshold=5)
        assert state.consecutive_misses == 0


# ── Status change ─────────────────────────────────────────────────────────────


class TestStatusChange:
    def test_degraded_status_fires_alert(self):
        state = WatchdogState()
        evaluate(_ok(), state, miss_threshold=3)  # prime last_status
        alerts = evaluate(_ok(status="degraded"), state, miss_threshold=3)
        assert any("degraded" in a for a in alerts)

    def test_degraded_status_fires_only_once_per_value(self):
        state = WatchdogState()
        evaluate(_ok(), state, miss_threshold=3)
        evaluate(_ok(status="degraded"), state, miss_threshold=3)
        # Same "degraded" status again — already recorded, no new alert
        alerts = evaluate(_ok(status="degraded"), state, miss_threshold=3)
        assert not any("degraded" in a for a in alerts)

    def test_ok_status_no_alert_on_first_poll(self):
        state = WatchdogState()
        alerts = evaluate(_ok(), state, miss_threshold=3)
        # No prior status — should not fire
        assert not any("degraded" in a for a in alerts)

    def test_status_returns_to_ok_no_alert(self):
        state = WatchdogState()
        state.last_status = "ok"
        alerts = evaluate(_ok(status="ok"), state, miss_threshold=3)
        assert not any("degraded" in a for a in alerts)


# ── IBKR data-connected flip ──────────────────────────────────────────────────


class TestIbkrDataFlip:
    def test_true_to_false_fires_alert(self):
        state = WatchdogState()
        state.last_ibkr_data = True
        alerts = evaluate(_ok(ibkr_data_connected=False), state, miss_threshold=3)
        assert any("IBKR data feed" in a for a in alerts)
        assert state.last_ibkr_data is False

    def test_false_to_true_no_alert(self):
        """Data reconnecting does not fire an alert (only disconnect fires)."""
        state = WatchdogState()
        state.last_ibkr_data = False
        alerts = evaluate(_ok(ibkr_data_connected=True), state, miss_threshold=3)
        assert not any("IBKR" in a for a in alerts)

    def test_already_false_no_repeat_alert(self):
        """If data was already False, no new alert on consecutive poll."""
        state = WatchdogState()
        state.last_ibkr_data = False
        alerts = evaluate(_ok(ibkr_data_connected=False), state, miss_threshold=3)
        assert not any("IBKR" in a for a in alerts)

    def test_first_poll_with_false_no_alert(self):
        """Initial state is None — False on first poll should not fire."""
        state = WatchdogState()
        assert state.last_ibkr_data is None
        alerts = evaluate(_ok(ibkr_data_connected=False), state, miss_threshold=3)
        assert not any("IBKR" in a for a in alerts)


# ── Kill-switch ───────────────────────────────────────────────────────────────


class TestKillSwitch:
    def test_false_to_true_fires_alert(self):
        state = WatchdogState()
        state.last_kill_switch = False
        alerts = evaluate(_ok(kill_switch_active=True), state, miss_threshold=3)
        assert any("Kill switch" in a for a in alerts)

    def test_already_true_no_repeat_alert(self):
        state = WatchdogState()
        state.last_kill_switch = True
        alerts = evaluate(_ok(kill_switch_active=True), state, miss_threshold=3)
        assert not any("Kill switch" in a for a in alerts)

    def test_true_to_false_no_alert(self):
        """Kill switch clearing does not fire an alert."""
        state = WatchdogState()
        state.last_kill_switch = True
        alerts = evaluate(_ok(kill_switch_active=False), state, miss_threshold=3)
        assert not any("Kill switch" in a for a in alerts)

    def test_none_initial_no_alert(self):
        """Initial last_kill_switch=None + True on first poll — should alert."""
        state = WatchdogState()
        assert state.last_kill_switch is None
        alerts = evaluate(_ok(kill_switch_active=True), state, miss_threshold=3)
        assert any("Kill switch" in a for a in alerts)


# ── Combined scenarios ────────────────────────────────────────────────────────


class TestCombined:
    def test_multiple_conditions_on_same_poll_all_fire(self):
        """If status=degraded AND kill_switch=True simultaneously, both alerts fire."""
        state = WatchdogState()
        state.last_status = "ok"
        state.last_kill_switch = False
        alerts = evaluate(
            {"status": "degraded", "ibkr_data_connected": True, "kill_switch_active": True},
            state,
            miss_threshold=3,
        )
        assert any("degraded" in a for a in alerts)
        assert any("Kill switch" in a for a in alerts)

    def test_down_then_recovery_clears_state(self):
        """Full cycle: down → recovery → subsequent healthy poll = quiet."""
        state = WatchdogState()
        for _ in range(3):
            evaluate(None, state, miss_threshold=3)
        evaluate(_ok(), state, miss_threshold=3)  # recovery
        alerts = evaluate(_ok(), state, miss_threshold=3)  # should be quiet now
        assert alerts == []
