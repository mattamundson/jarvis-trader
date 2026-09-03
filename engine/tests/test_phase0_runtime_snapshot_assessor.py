from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "assess_phase0_runtime_snapshot.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_phase0_runtime_snapshot_assessor", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(now: dt.datetime) -> dict:
    endpoint = {"reachable": True, "safe_health": {}}
    return {
        "artifact": "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
        "schema_version": 1,
        "captured_at_utc": now.isoformat(),
        "read_only_runtime_probe": True,
        "secrets_included": False,
        "repository": {"head": "abc123", "branch": "master", "status_porcelain_count": 0},
        "ports": {
            "engine_8010_open": True,
            "dashboard_3010_open": True,
            "ib_paper_4002_open": True,
            "ib_live_4001_open": False,
        },
        "api": {
            "config_overview": {
                "reachable": True,
                "safe_config": {
                    "LIVE_TRADING_ENABLED": False,
                    "PAPER_TRADING": True,
                    "IBKR_PAPER_MODE": True,
                    "IBKR_PORT": 4002,
                },
            },
            "health": {"reachable": True, "safe_health": {"live_trading": False}},
            "health_full": {"reachable": True, "safe_health": {"live_trading": False}},
            "safety_status": {
                "reachable": True,
                "safe_health": {
                    "kill_switch_active": False,
                    "hard_halt": False,
                    "halted": False,
                    "safety_state": "verified_safe",
                    "safety_state_verified": True,
                },
            },
            "eligibility": {
                "reachable": True,
                "summary": {"total": 1, "tradeable": 1, "enabled": 1, "disagreements": 0},
                "symbols": [],
            },
            "backup_status": endpoint,
        },
    }


def test_clean_snapshot_is_only_ready_for_operator_review():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    result = module.assess_snapshot(_snapshot(now), now=now)

    assert result["status"] == "READY_FOR_OPERATOR_REVIEW"
    assert result["blocker_count"] == 0
    assert result["authorization"]["a01_auto_close_allowed"] is False
    assert result["authorization"]["trading_authorized"] is False
    assert result["authorization"]["operator_disposition_required"] is True


def test_live_loaded_config_blocks_assessment():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    snapshot = _snapshot(now)
    snapshot["api"]["config_overview"]["safe_config"]["LIVE_TRADING_ENABLED"] = True

    result = module.assess_snapshot(snapshot, now=now)
    codes = {item["code"] for item in result["findings"]}

    assert result["status"] == "BLOCKED"
    assert "LIVE_ENABLED" in codes


def test_unreachable_required_endpoint_blocks_assessment():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    snapshot = _snapshot(now)
    snapshot["api"]["safety_status"] = {"reachable": False, "error": "timeout"}

    result = module.assess_snapshot(snapshot, now=now)
    codes = {item["code"] for item in result["findings"]}

    assert result["status"] == "BLOCKED"
    assert "ENDPOINT_UNREACHABLE" in codes


def test_stale_snapshot_blocks_assessment():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 30, tzinfo=dt.timezone.utc)
    captured = now - dt.timedelta(minutes=16)

    result = module.assess_snapshot(_snapshot(captured), now=now, max_age_minutes=15)
    codes = {item["code"] for item in result["findings"]}

    assert result["status"] == "BLOCKED"
    assert "STALE_SNAPSHOT" in codes


def test_unknown_safety_state_and_eligibility_disagreement_block():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    snapshot = _snapshot(now)
    snapshot["api"]["safety_status"]["safe_health"].update(
        {"safety_state": "state_unknown", "safety_state_verified": False}
    )
    snapshot["api"]["eligibility"]["summary"]["disagreements"] = 1

    result = module.assess_snapshot(snapshot, now=now)
    codes = {item["code"] for item in result["findings"]}

    assert "SAFETY_STATE_UNKNOWN" in codes
    assert "ELIGIBILITY_DISAGREEMENT" in codes


def test_live_port_is_warning_not_authorization():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    snapshot = _snapshot(now)
    snapshot["ports"]["ib_live_4001_open"] = True

    result = module.assess_snapshot(snapshot, now=now)
    codes = {item["code"] for item in result["findings"]}

    assert result["status"] == "READY_FOR_OPERATOR_REVIEW"
    assert "IB_LIVE_PORT_OPEN" in codes
    assert "BOTH_IB_PORTS_OPEN" in codes
    assert result["authorization"]["trading_authorized"] is False


def test_invalid_artifact_never_appears_ready():
    module = _load_script()
    now = dt.datetime(2026, 9, 3, 5, 0, tzinfo=dt.timezone.utc)
    snapshot = _snapshot(now)
    snapshot["artifact"] = "wrong"

    result = module.assess_snapshot(snapshot, now=now)

    assert result["status"] == "BLOCKED"
    assert result["blocker_count"] >= 1
