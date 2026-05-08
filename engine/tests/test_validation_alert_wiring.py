"""Smoke tests for ValidationAlertManager alert wiring.

Verifies that:
1. evaluate_gates() fires GateAlert events on PASS->FAIL and FAIL->PASS transitions
2. No spurious alerts are fired when gate status is stable
3. _send_notification is safe to call synchronously (no event loop, no discord)
4. GateAlert dataclass fields are populated correctly
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from notifications.validation_alerts import GateAlert, ValidationAlertManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> ValidationAlertManager:
    alert_file = str(tmp_path / "test_alerts.json")
    return ValidationAlertManager(alert_file=alert_file)


def _passing_metrics() -> dict:
    """All gates pass."""
    return {
        "profit_factor": 2.5,  # target 2.0 gte
        "sharpe_ratio": 2.0,  # target 1.5 gte
        "win_rate_pct": 60.0,  # target 55.0 gte
        "total_trades": 70,  # target 60 gte
        "max_drawdown_pct": 10.0,  # target 15.0 lte
        "days_active": 35,  # target 30 gte
    }


def _failing_metrics() -> dict:
    """All gates fail."""
    return {
        "profit_factor": 0.9,
        "sharpe_ratio": 0.5,
        "win_rate_pct": 40.0,
        "total_trades": 10,
        "max_drawdown_pct": 20.0,
        "days_active": 5,
    }


# ---------------------------------------------------------------------------
# Core wiring tests
# ---------------------------------------------------------------------------


def test_no_alerts_on_first_evaluation(tmp_path: Path) -> None:
    """First call establishes baseline; no transitions possible."""
    mgr = _make_manager(tmp_path)
    alerts = mgr.evaluate_gates(_passing_metrics())
    assert alerts == [], f"Expected no alerts on first evaluation, got: {alerts}"


def test_no_alerts_when_status_stable(tmp_path: Path) -> None:
    """Repeated same-status evaluations produce no alerts."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())  # establish baseline
    alerts = mgr.evaluate_gates(_passing_metrics())  # same status again
    assert alerts == [], f"Spurious alerts on stable status: {alerts}"


def test_pass_to_fail_transition_fires_alert(tmp_path: Path) -> None:
    """profit_factor dropping below 2.0 must fire a PASS->FAIL alert."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())  # baseline: all PASS

    failing = _passing_metrics()
    failing["profit_factor"] = 0.8  # below 2.0 target
    alerts = mgr.evaluate_gates(failing)

    pf_alerts = [a for a in alerts if a.gate_name == "profit_factor"]
    assert len(pf_alerts) == 1
    assert pf_alerts[0].old_status == "PASS"
    assert pf_alerts[0].new_status == "FAIL"
    assert pf_alerts[0].current_value == pytest.approx(0.8)


def test_fail_to_pass_transition_fires_alert(tmp_path: Path) -> None:
    """profit_factor recovering above 2.0 must fire a FAIL->PASS alert."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_failing_metrics())  # baseline: all FAIL

    recovering = _failing_metrics()
    recovering["profit_factor"] = 3.0  # above 2.0 target
    alerts = mgr.evaluate_gates(recovering)

    pf_alerts = [a for a in alerts if a.gate_name == "profit_factor"]
    assert len(pf_alerts) == 1
    assert pf_alerts[0].old_status == "FAIL"
    assert pf_alerts[0].new_status == "PASS"


def test_max_drawdown_gate_direction(tmp_path: Path) -> None:
    """max_drawdown is a 'lte' gate — exceeding it causes FAIL."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())  # baseline: DD 10% -> PASS

    worse = _passing_metrics()
    worse["max_drawdown_pct"] = 16.0  # above 15.0 target -> FAIL
    alerts = mgr.evaluate_gates(worse)

    dd_alerts = [a for a in alerts if a.gate_name == "max_drawdown"]
    assert len(dd_alerts) == 1
    assert dd_alerts[0].new_status == "FAIL"


def test_multiple_gates_can_flip_simultaneously(tmp_path: Path) -> None:
    """Multiple gates flipping in one evaluation must each produce an alert."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())  # baseline

    # Flip 3 gates to FAIL
    mixed = _passing_metrics()
    mixed["profit_factor"] = 0.5
    mixed["sharpe_ratio"] = 0.2
    mixed["total_trades"] = 5
    alerts = mgr.evaluate_gates(mixed)

    flipped_gates = {a.gate_name for a in alerts}
    assert "profit_factor" in flipped_gates
    assert "sharpe_ratio" in flipped_gates
    assert "trade_count" in flipped_gates


def test_gate_alert_fields_populated(tmp_path: Path) -> None:
    """GateAlert must have all required fields populated correctly."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())

    failing = _passing_metrics()
    failing["profit_factor"] = 1.0
    alerts = mgr.evaluate_gates(failing)

    pf_alert = next((a for a in alerts if a.gate_name == "profit_factor"), None)
    assert pf_alert is not None
    assert isinstance(pf_alert, GateAlert)
    assert pf_alert.gate_name == "profit_factor"
    assert pf_alert.old_status == "PASS"
    assert pf_alert.new_status == "FAIL"
    assert pf_alert.current_value == pytest.approx(1.0)
    assert pf_alert.target_value == 2.0
    assert pf_alert.timestamp  # non-empty string


def test_alert_history_persisted_to_json(tmp_path: Path) -> None:
    """Alerts must be written to the JSON history file."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())

    failing = _passing_metrics()
    failing["profit_factor"] = 0.5
    mgr.evaluate_gates(failing)

    alert_file = tmp_path / "test_alerts.json"
    assert alert_file.exists()
    data = json.loads(alert_file.read_text())
    assert "alerts" in data
    assert len(data["alerts"]) >= 1
    assert data["alerts"][0]["gate_name"] == "profit_factor"


def test_get_current_gate_status_reflects_last_evaluation(tmp_path: Path) -> None:
    """get_current_gate_status must reflect the most recent evaluate_gates call."""
    mgr = _make_manager(tmp_path)
    mgr.evaluate_gates(_passing_metrics())
    status = mgr.get_current_gate_status()
    assert status["profit_factor"] == "PASS"
    assert status["trade_count"] == "PASS"

    failing = _passing_metrics()
    failing["profit_factor"] = 0.5
    mgr.evaluate_gates(failing)
    status = mgr.get_current_gate_status()
    assert status["profit_factor"] == "FAIL"
    assert status["trade_count"] == "PASS"  # unchanged


def test_missing_metric_skipped_gracefully(tmp_path: Path) -> None:
    """Metrics not in the input dict must be skipped without raising."""
    mgr = _make_manager(tmp_path)
    partial = {"profit_factor": 2.5}  # only one of six metrics present
    alerts = mgr.evaluate_gates(partial)
    # No crash; only the provided metric is evaluated
    assert isinstance(alerts, list)


def test_send_notification_safe_without_event_loop(tmp_path: Path) -> None:
    """_send_notification must not crash when called outside an async event loop."""
    mgr = _make_manager(tmp_path)
    alert = GateAlert(
        gate_name="profit_factor",
        old_status="PASS",
        new_status="FAIL",
        current_value=0.5,
        target_value=2.0,
        timestamp="2026-05-08T00:00:00",
    )
    # Should be a no-op / graceful fallback — must not raise
    mgr._send_notification(alert)
