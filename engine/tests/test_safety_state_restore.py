"""Failure-mode tests for persisted SafetyLayer startup state."""

from __future__ import annotations

import asyncio
import sqlite3

from risk.safety_layer import SafetyLayer, SafetyState


def _db_with_state(tmp_path, value: str | None):
    path = tmp_path / "safety-state.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT)")
    if value is not None:
        conn.execute(
            "INSERT INTO system_state (key, value) VALUES (?, ?)",
            ("kill_switch_active", value),
        )
    conn.commit()
    conn.close()
    return path


def test_explicit_false_is_verified_safe(mock_settings, tmp_path):
    safety = SafetyLayer(mock_settings, db_path=str(_db_with_state(tmp_path, "false")))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.VERIFIED_SAFE.value
    assert status["safety_state_verified"] is True
    assert status["is_killed"] is False
    assert safety._check_kill_switch().approved is True


def test_explicit_true_is_verified_halted(mock_settings, tmp_path):
    safety = SafetyLayer(mock_settings, db_path=str(_db_with_state(tmp_path, "true")))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.VERIFIED_HALTED.value
    assert status["safety_state_verified"] is True
    assert status["is_killed"] is True
    assert safety._check_kill_switch().approved is False


def test_missing_table_is_unknown_and_blocks_new_exposure(mock_settings, tmp_path):
    path = tmp_path / "missing-table.db"
    sqlite3.connect(path).close()

    safety = SafetyLayer(mock_settings, db_path=str(path))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.STATE_UNKNOWN.value
    assert status["safety_state_verified"] is False
    assert status["is_killed"] is True
    assert "unknown" in safety._check_kill_switch().rejection_reason.lower()


def test_missing_key_is_unknown(mock_settings, tmp_path):
    safety = SafetyLayer(mock_settings, db_path=str(_db_with_state(tmp_path, None)))

    assert safety.get_status()["safety_state"] == SafetyState.STATE_UNKNOWN.value
    assert safety.is_killed is True


def test_invalid_value_is_unknown(mock_settings, tmp_path):
    safety = SafetyLayer(mock_settings, db_path=str(_db_with_state(tmp_path, "maybe")))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.STATE_UNKNOWN.value
    assert status["safety_state_error"] == "ValueError"
    assert safety.is_killed is True


def test_corrupt_database_is_unknown(mock_settings, tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not a sqlite database")

    safety = SafetyLayer(mock_settings, db_path=str(path))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.STATE_UNKNOWN.value
    assert status["safety_state_error"] == "DatabaseError"
    assert safety.is_killed is True


def test_locked_or_unavailable_database_is_unknown(mock_settings, tmp_path, monkeypatch):
    path = _db_with_state(tmp_path, "false")

    def fail_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    safety = SafetyLayer(mock_settings, db_path=str(path))

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.STATE_UNKNOWN.value
    assert status["safety_state_error"] == "OperationalError"
    assert safety.is_killed is True


def test_submit_paper_order_rejects_unknown_before_gateway(mock_settings, tmp_path):
    path = tmp_path / "missing-table.db"
    sqlite3.connect(path).close()
    safety = SafetyLayer(mock_settings, db_path=str(path))

    result = asyncio.run(
        safety.submit_paper_order(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=5000.0,
        )
    )

    assert result == {
        "approved": False,
        "reason": (
            "Safety state unknown: persisted kill-switch state could not be verified"
        ),
        "order_id": None,
        "routed_to_ib": False,
    }


def test_no_persistence_remains_explicitly_not_configured(mock_settings):
    safety = SafetyLayer(mock_settings, db_path=None)

    status = safety.get_status()
    assert status["safety_state"] == SafetyState.NOT_CONFIGURED.value
    assert status["safety_state_verified"] is False
    assert status["is_killed"] is False


def test_unknown_state_propagates_to_parallel_disabled_account_status(
    mock_settings, tmp_path
):
    path = tmp_path / "missing-table.db"
    sqlite3.connect(path).close()
    safety = SafetyLayer(mock_settings, db_path=str(path))

    state = safety.get_per_account_kill_state("paper-account")

    assert state["active"] is True
    assert state["reason"] == "persisted safety state unknown"


def test_bracket_submission_rejects_unknown_before_gateway(mock_settings, tmp_path):
    path = tmp_path / "missing-table.db"
    sqlite3.connect(path).close()
    safety = SafetyLayer(mock_settings, db_path=str(path))

    result = asyncio.run(
        safety.submit_paper_bracket_order(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=5000.0,
            stop_loss=4990.0,
            take_profit=5020.0,
        )
    )

    assert result["approved"] is False
    assert "unknown" in result["reason"].lower()
    assert result["routed_to_ib"] is False
