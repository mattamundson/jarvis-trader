"""Contract test — SafetyLayer.get_status() kill-switch key invariant.

Background (2026-06-15 inert-kill-switch defect)
------------------------------------------------
``SafetyLayer.get_status()`` historically returned the latched halt under a
single key, ``is_killed``. But 12+ in-process gates read it under a *different*
name, ``kill_switch_active`` (the public field name that the HTTP routers map
to). Because ``get_status()`` never emitted that key, ``dict.get(...)`` returned
``None`` (falsey) and every one of those gates silently bypassed the kill
switch — the scanner, the watchlist scheduler, the market-open scan, the
autonomous enqueue gate, the ``/pipeline/run`` handler, the approval-queue
submit gate, ``/scan-now``, and the LLM trader/risk agents.

The robust fix is at the *source*: ``get_status()`` now emits BOTH keys with the
same value, so no caller can read the wrong one. These tests lock that contract
so a future "dedup" of the two keys can never re-introduce the bypass.
"""

import pytest

from risk.safety_layer import KillSwitchReason, SafetyLayer

# Every name that any in-process caller reads off get_status() to decide the
# kill-switch gate. get_status() MUST emit all of them, always in lock-step.
KILL_KEYS = ("is_killed", "kill_switch_active")


@pytest.fixture
def safety(mock_settings):
    return SafetyLayer(mock_settings)


def test_get_status_emits_both_kill_keys(safety):
    """Both halt key names are present and boolean — the missing-key bug class."""
    status = safety.get_status()
    for key in KILL_KEYS:
        assert key in status, f"get_status() dropped {key!r} — a gate reading it bypasses the halt"
        assert isinstance(status[key], bool), f"{key!r} must be a real bool, not {type(status[key])}"


def test_kill_keys_false_when_inactive(safety):
    status = safety.get_status()
    assert all(status[k] is False for k in KILL_KEYS), "kill keys must be False before activation"


def test_kill_keys_true_and_lockstep_when_active(safety):
    """Activating the latch flips BOTH keys together — never one without the other."""
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "contract test")
    status = safety.get_status()
    assert all(status[k] is True for k in KILL_KEYS), "every kill key must be True once armed"
    # The load-bearing invariant: the two names are always equal.
    assert len({status[k] for k in KILL_KEYS}) == 1, "kill keys diverged — bypass risk"
    assert status["kill_switch_reason"] == KillSwitchReason.MANUAL.value


def test_kill_keys_clear_together_on_deactivate(safety):
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "contract test")
    safety.deactivate_kill_switch()
    status = safety.get_status()
    assert all(status[k] is False for k in KILL_KEYS), "kill keys must clear together on deactivate"


def test_kill_keys_stay_lockstep_across_transitions(safety):
    """is_killed and kill_switch_active are identical at every step of the cycle."""
    def lockstep(label):
        s = safety.get_status()
        vals = {s[k] for k in KILL_KEYS}
        assert len(vals) == 1, f"{label}: kill keys diverged {[(k, s[k]) for k in KILL_KEYS]}"
        return s["is_killed"]

    assert lockstep("initial") is False
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "t")
    assert lockstep("after activate") is True
    safety.deactivate_kill_switch()
    assert lockstep("after deactivate") is False
