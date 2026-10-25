from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "jarvis_alert_bridge.py"
SPEC = importlib.util.spec_from_file_location("jarvis_alert_bridge", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


def snapshot(**overrides):
    base = {
        "engine_up": True,
        "dashboard_up": True,
        "gateway_open": True,
        "kill_switch": False,
        "trading_mode": "PAPER",
        "data_fresh": True,
        "drawdown_pct": 5.0,
        "signals": {},
    }
    base.update(overrides)
    return base


def test_detects_and_clears_requested_operational_faults():
    healthy = snapshot()
    failed = snapshot(
        engine_up=False,
        dashboard_up=False,
        gateway_open=False,
        data_fresh=False,
    )

    detected = BRIDGE.diff(healthy, failed)
    assert any("ENGINE DOWN" in line for line in detected)
    assert any("DASHBOARD DOWN" in line for line in detected)
    assert any("GATEWAY LOST" in line for line in detected)
    assert any("MARKET DATA STALE" in line for line in detected)

    recovered = BRIDGE.diff(failed, healthy)
    assert any("ENGINE RECOVERED" in line for line in recovered)
    assert any("DASHBOARD RECOVERED" in line for line in recovered)
    assert any("GATEWAY RESTORED" in line for line in recovered)


def test_state_persistence_failure_is_a_cron_failure(monkeypatch, capsys):
    monkeypatch.setattr(BRIDGE, "load_state", lambda: snapshot())
    monkeypatch.setattr(BRIDGE, "take_snapshot", snapshot)
    monkeypatch.setattr(BRIDGE, "save_state", lambda _state: False)

    assert BRIDGE.main() == 1
    assert "could not persist state" in capsys.readouterr().out
