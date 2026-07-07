"""
Tests for the operations dashboard JSON endpoint.

Verifies the structure and typing of build_dashboard_data() without
requiring a running engine — all external calls are mocked.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_engine_health_ok() -> Dict[str, Any]:
    return {
        "reachable": True,
        "status": "ok",
        "tradingview_mcp_healthy": True,
        "llm_path_healthy": True,
        "ibkr_exec": {"connected": True},
        "ibkr_data": {"connected": True},
        "kill_switch_active": False,
        "polled_at": "2026-05-07T12:00:00+00:00",
    }


def _mock_engine_health_down() -> Dict[str, Any]:
    return {
        "reachable": True,
        "status": "ok",
        "tradingview_mcp_healthy": False,
        "llm_path_healthy": False,
        "ibkr_exec": {"connected": False},
        "ibkr_data": {"connected": False},
        "kill_switch_active": False,
        "polled_at": "2026-05-07T12:00:00+00:00",
    }


def _mock_engine_unreachable() -> Dict[str, Any]:
    return {
        "reachable": False,
        "status": "unreachable",
        "tradingview_mcp_healthy": False,
        "llm_path_healthy": False,
        "ibkr_exec": {"connected": False},
        "ibkr_data": {"connected": False},
        "kill_switch_active": False,
        "polled_at": "2026-05-07T12:00:00+00:00",
        "error": "Connection refused",
    }


def _mock_pnl(target_date=None) -> Dict[str, Any]:
    return {
        "pnl": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "source": "error",
        "error": "no data",
    }


def _mock_readiness() -> Dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pass_count": 0,
        "consecutive_passing_days": 0,
        "days_to_live": 14,
        "gates": [],
        "source": "error",
    }


def _build_with_health(engine_health_fn) -> Dict[str, Any]:
    import engine.api.operations_dashboard as mod

    with (
        patch.object(mod, "_compute_today_pnl", _mock_pnl),
        patch.object(mod, "_get_live_readiness", _mock_readiness),
        patch.object(mod, "_get_uptime_7d", lambda: [False] * 7),
        patch.object(mod, "_get_open_positions_count", lambda: 0),
        patch.object(mod, "_read_latest_report", lambda *a, **kw: None),
        patch.object(mod, "_get_career_ops_recap", lambda: None),
        patch.object(mod, "_get_engine_health", engine_health_fn),
    ):
        return mod.build_dashboard_data(target_date=date(2026, 5, 7))


# ---------------------------------------------------------------------------
# Tests — top-level shape
# ---------------------------------------------------------------------------


def test_has_required_top_level_keys() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    required = {
        "generated_at",
        "report_date",
        "health",
        "today",
        "live_readiness",
        "engine_health",
        "uptime_7d",
        "reports",
    }
    missing = required - data.keys()
    assert not missing, f"Missing top-level keys: {missing}"


def test_report_date_matches_target() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    assert data["report_date"] == "2026-05-07"


def test_generated_at_is_iso_string() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    assert isinstance(data["generated_at"], str)
    assert "T" in data["generated_at"]


# ---------------------------------------------------------------------------
# Tests — health widget (T12 additions)
# ---------------------------------------------------------------------------


def test_health_widget_has_four_fields() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    assert set(data["health"].keys()) == {
        "tv_mcp_healthy",
        "llm_path_healthy",
        "ibkr_data_connected",
        "ibkr_execution_connected",
    }


def test_health_widget_all_true_when_engine_healthy() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    h = data["health"]
    assert h["tv_mcp_healthy"] is True
    assert h["llm_path_healthy"] is True
    assert h["ibkr_data_connected"] is True
    assert h["ibkr_execution_connected"] is True


def test_health_widget_all_false_when_components_down() -> None:
    data = _build_with_health(_mock_engine_health_down)
    h = data["health"]
    assert h["tv_mcp_healthy"] is False
    assert h["llm_path_healthy"] is False
    assert h["ibkr_data_connected"] is False
    assert h["ibkr_execution_connected"] is False


def test_health_widget_all_none_when_unreachable() -> None:
    """When the engine is unreachable, all 4 fields should be None (not False)."""
    data = _build_with_health(_mock_engine_unreachable)
    h = data["health"]
    assert h["tv_mcp_healthy"] is None, "unreachable engine must yield None, not False"
    assert h["llm_path_healthy"] is None
    assert h["ibkr_data_connected"] is None
    assert h["ibkr_execution_connected"] is None


def test_health_widget_mixed_states() -> None:
    def mixed() -> Dict[str, Any]:
        return {
            "reachable": True,
            "status": "ok",
            "tradingview_mcp_healthy": True,
            "llm_path_healthy": False,
            "ibkr_exec": {"connected": True},
            "ibkr_data": {"connected": False},
            "kill_switch_active": False,
            "polled_at": "2026-05-07T12:00:00+00:00",
        }

    data = _build_with_health(mixed)
    h = data["health"]
    assert h["tv_mcp_healthy"] is True
    assert h["llm_path_healthy"] is False
    assert h["ibkr_execution_connected"] is True
    assert h["ibkr_data_connected"] is False


def test_health_widget_ibkr_connected_key_unwrapped() -> None:
    """ibkr_exec/ibkr_data are returned as dicts — the 'connected' field must be unwrapped to bool."""

    def health_with_dict_ibkr() -> Dict[str, Any]:
        return {
            "reachable": True,
            "status": "ok",
            "tradingview_mcp_healthy": True,
            "llm_path_healthy": True,
            "ibkr_exec": {"connected": True, "extra_field": "ignored"},
            "ibkr_data": {"connected": False, "extra_field": "ignored"},
            "kill_switch_active": False,
            "polled_at": "2026-05-07T12:00:00+00:00",
        }

    data = _build_with_health(health_with_dict_ibkr)
    assert data["health"]["ibkr_execution_connected"] is True
    assert data["health"]["ibkr_data_connected"] is False


def test_health_widget_is_json_serializable() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    serialized = json.dumps(data["health"])
    parsed = json.loads(serialized)
    assert set(parsed.keys()) == {
        "tv_mcp_healthy",
        "llm_path_healthy",
        "ibkr_data_connected",
        "ibkr_execution_connected",
    }


# ---------------------------------------------------------------------------
# Tests — backward compat: engine_health section not removed
# ---------------------------------------------------------------------------


def test_engine_health_still_present_in_response() -> None:
    """The 'health' widget is additive — engine_health must remain unchanged."""
    data = _build_with_health(_mock_engine_health_ok)
    assert "engine_health" in data
    eh = data["engine_health"]
    assert "reachable" in eh
    assert "tradingview_mcp_healthy" in eh
    assert "llm_path_healthy" in eh


def test_today_section_present() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    assert "today" in data
    assert "pnl" in data["today"]


def test_uptime_7d_is_list_of_7() -> None:
    data = _build_with_health(_mock_engine_health_ok)
    assert isinstance(data["uptime_7d"], list)
    assert len(data["uptime_7d"]) == 7
