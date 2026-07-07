"""State-transition-only kill-switch side effects (#6 — alert spam fix).

The breach checks call activate_kill_switch() on every scan while a breach
persists. Previously each call re-fired the OpenClaw alert, re-logged, and
re-scheduled the bracket cancel (~10/min spam). Side effects must now run only
on a real transition (inactive→active) or a change of reason; the latch itself
is unchanged (still needs a manual deactivate).

We use _persist_kill_switch_state as the observable proxy for "side effects
ran" — it sits alongside the alert/cancel scheduling inside the guarded block.
"""

from unittest.mock import MagicMock

import pytest

from risk.safety_layer import KillSwitchReason, SafetyLayer


@pytest.fixture
def safety(mock_settings):
    s = SafetyLayer(mock_settings)
    s._persist_kill_switch_state = MagicMock()  # spy on the guarded side effect
    return s


def test_repeated_same_reason_runs_side_effects_once(safety):
    safety.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, "dd breach")
    for _ in range(9):  # simulate 9 more scans while still breached
        safety.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, "dd breach")
    assert safety._persist_kill_switch_state.call_count == 1
    assert safety.is_killed is True  # latch still engaged


def test_reason_change_refires_side_effects(safety):
    safety.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, "dd")
    safety.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT, "loss")
    assert safety._persist_kill_switch_state.call_count == 2
    assert safety.get_status()["kill_switch_reason"] == KillSwitchReason.DAILY_LOSS_LIMIT.value


def test_reactivation_keeps_latch_and_status(safety):
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "x")
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "x")
    status = safety.get_status()
    assert status["is_killed"] is True
    assert status["kill_switch_active"] is True  # contract alias still lock-step


def test_deactivate_then_reactivate_refires(safety):
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "x")
    safety.deactivate_kill_switch()
    safety._persist_kill_switch_state.reset_mock()  # isolate the re-activation
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "x")  # fresh transition
    assert safety._persist_kill_switch_state.call_count == 1
    assert safety.is_killed is True
