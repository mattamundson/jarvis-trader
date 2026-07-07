"""Tests for P3-43 — tiered kill-switch escalation (HaltLevel enum + emergency_flatten_and_halt).

Verifies:
  - current_halt_level synthesises existing kill-switch and loss-tracker state correctly
  - NORMAL → SOFT_HALT → HARD_HALT → EMERGENCY_FLATTEN progression
  - emergency_flatten_and_halt() activates kill switch and calls flatten_all_positions()
  - deactivate_kill_switch() clears the emergency flatten flag (clean slate for re-auth)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk.safety_layer import HaltLevel, KillSwitchReason, SafetyLayer


@pytest.fixture
def safety(mock_settings):
    """Isolated SafetyLayer — no DB, no IB gateway."""
    return SafetyLayer(mock_settings)


# ─────────────────────────────────────────────────────────────────────────────
# current_halt_level — read-only synthesis
# ─────────────────────────────────────────────────────────────────────────────


def test_halt_level_normal_when_clean(safety):
    """No halts active → NORMAL."""
    assert safety.current_halt_level is HaltLevel.NORMAL


def test_halt_level_soft_halt_when_loss_tracker_reduced(safety):
    """Loss tracker multiplier < 1.0 → SOFT_HALT (orders still accepted, size reduced)."""
    mock_tracker = MagicMock()
    mock_tracker.get_position_size_multiplier.return_value = 0.5
    safety._loss_tracker = mock_tracker
    assert safety.current_halt_level is HaltLevel.SOFT_HALT


def test_halt_level_hard_halt_when_kill_switch_active(safety):
    """Kill switch active → HARD_HALT."""
    safety.activate_kill_switch(KillSwitchReason.MANUAL, "test")
    assert safety.current_halt_level is HaltLevel.HARD_HALT


def test_halt_level_emergency_flatten_trumps_hard_halt(safety):
    """EMERGENCY_FLATTEN bit set + kill switch active → EMERGENCY_FLATTEN (highest tier)."""
    safety.activate_kill_switch(KillSwitchReason.EMERGENCY_FLATTEN, "test")
    safety._emergency_flatten_activated = True
    assert safety.current_halt_level is HaltLevel.EMERGENCY_FLATTEN


def test_hard_halt_trumps_soft_halt(safety):
    """Kill switch active + loss tracker soft-halted → HARD_HALT wins."""
    mock_tracker = MagicMock()
    mock_tracker.get_position_size_multiplier.return_value = 0.0
    safety._loss_tracker = mock_tracker
    safety.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT, "test")
    assert safety.current_halt_level is HaltLevel.HARD_HALT


# ─────────────────────────────────────────────────────────────────────────────
# emergency_flatten_and_halt()
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_flatten_activates_kill_switch(safety):
    """emergency_flatten_and_halt() must activate the kill switch synchronously."""
    safety._ib_gateway = AsyncMock()
    safety._ib_gateway.get_positions = AsyncMock(return_value=[])

    await safety.emergency_flatten_and_halt(reason="test escalation")

    assert safety.is_killed is True
    assert safety._kill_switch_reason is KillSwitchReason.EMERGENCY_FLATTEN


@pytest.mark.asyncio
async def test_emergency_flatten_calls_flatten_all_positions(safety):
    """emergency_flatten_and_halt() must call flatten_all_positions() and return its results."""
    mock_positions = [{"symbol": "MES", "position": 1}]
    safety._ib_gateway = AsyncMock()
    safety._ib_gateway.get_positions = AsyncMock(return_value=mock_positions)
    safety._ib_gateway.place_paper_order = AsyncMock(return_value="oid-001")

    result = await safety.emergency_flatten_and_halt(reason="test")

    assert result["halt_level"] == HaltLevel.EMERGENCY_FLATTEN.value
    assert result["kill_switch_activated"] is True
    assert "MES" in result["flattened"]
    assert safety.current_halt_level is HaltLevel.EMERGENCY_FLATTEN


@pytest.mark.asyncio
async def test_deactivate_clears_emergency_flatten_flag(safety):
    """Human deactivation must clear the emergency flatten flag — full clean slate."""
    safety._ib_gateway = AsyncMock()
    safety._ib_gateway.get_positions = AsyncMock(return_value=[])
    await safety.emergency_flatten_and_halt(reason="test")
    assert safety.current_halt_level is HaltLevel.EMERGENCY_FLATTEN

    safety.deactivate_kill_switch(authorized_by="human")

    assert safety._emergency_flatten_activated is False
    assert safety.is_killed is False
    assert safety.current_halt_level is HaltLevel.NORMAL
