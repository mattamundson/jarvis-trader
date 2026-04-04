"""system_state table + kill-switch SQLite persistence."""

from __future__ import annotations

import pytest

from database.manager import DatabaseManager
from risk.safety_layer import KillSwitchReason, SafetyLayer


@pytest.fixture
def mock_settings():
    from unittest.mock import MagicMock

    s = MagicMock()
    s.LIVE_TRADING_ENABLED = True
    s.REQUIRE_HUMAN_APPROVAL = True
    s.MAX_DAILY_LOSS_PCT = 0.02
    s.MAX_DRAWDOWN_PCT = 0.10
    return s


def test_system_state_mixin_roundtrip(tmp_path, mock_settings):
    _ = mock_settings
    db_path = tmp_path / "state.db"
    dm = DatabaseManager(str(db_path))
    dm.initialize()
    assert dm.get_system_state("k") is None
    dm.set_system_state("k", "v")
    assert dm.get_system_state("k") == "v"
    assert dm.delete_system_state("k") is True
    assert dm.get_system_state("k") is None


def test_kill_switch_persists_across_restarts(tmp_path, mock_settings):
    db_path = tmp_path / "ks.db"
    dm = DatabaseManager(str(db_path))
    dm.initialize()

    s1 = SafetyLayer(mock_settings, db_path=str(db_path))
    assert s1.is_killed is False
    s1.activate_kill_switch(KillSwitchReason.MANUAL, "persist test")
    assert s1.is_killed is True

    s2 = SafetyLayer(mock_settings, db_path=str(db_path))
    assert s2.is_killed is True
    assert s2._kill_switch_reason == KillSwitchReason.MANUAL

    s2.deactivate_kill_switch(authorized_by="pytest")
    assert s2.is_killed is False

    s3 = SafetyLayer(mock_settings, db_path=str(db_path))
    assert s3.is_killed is False
