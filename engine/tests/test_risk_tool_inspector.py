"""
Tests for risk/tool_inspector.py — ToolInspectionManager and 4 inspector classes.

Covers: InspectionResult priority escalation, LiquidityInspector deny path,
VolatilityInspector require_approval and deny paths, RiskInspector size bounds,
KillSwitchInspector, ToolInspectionManager.inspect_all aggregation.
"""

from __future__ import annotations

import pytest

from risk.tool_inspector import (
    InspectionResult,
    KillSwitchInspector,
    LiquidityInspector,
    RiskInspector,
    ToolInspectionManager,
    VolatilityInspector,
)

# ── LiquidityInspector ────────────────────────────────────────────────────────


class TestLiquidityInspector:
    def test_no_volume_in_context_allows(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {})
        assert result == InspectionResult.ALLOW
        assert msg == ""

    def test_volume_above_threshold_allows(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {"recent_volume": 5000.0})
        assert result == InspectionResult.ALLOW

    def test_volume_at_threshold_allows(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {"recent_volume": 1000.0})
        assert result == InspectionResult.ALLOW

    def test_volume_below_threshold_denies(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {"recent_volume": 500.0})
        assert result == InspectionResult.DENY
        assert "LiquidityInspector" in msg
        assert "place_order" in msg

    def test_non_numeric_volume_allows(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {"recent_volume": "bad"})
        assert result == InspectionResult.ALLOW

    def test_none_volume_allows(self):
        insp = LiquidityInspector(min_recent_volume=1000.0)
        result, msg = insp.inspect("place_order", {}, {"recent_volume": None})
        assert result == InspectionResult.ALLOW


# ── VolatilityInspector ───────────────────────────────────────────────────────


class TestVolatilityInspector:
    def test_no_vix_in_context_allows(self):
        insp = VolatilityInspector()
        result, msg = insp.inspect("place_order", {}, {})
        assert result == InspectionResult.ALLOW

    def test_low_vix_allows(self):
        insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        result, msg = insp.inspect("place_order", {}, {"vix": 20.0})
        assert result == InspectionResult.ALLOW

    def test_vix_between_thresholds_requires_approval(self):
        insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        result, msg = insp.inspect("place_order", {}, {"vix": 40.0})
        assert result == InspectionResult.REQUIRE_APPROVAL
        assert "VolatilityInspector" in msg
        assert "place_order" in msg

    def test_vix_above_deny_threshold_denies(self):
        insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        result, msg = insp.inspect("place_order", {}, {"vix": 60.0})
        assert result == InspectionResult.DENY
        assert "VolatilityInspector" in msg

    def test_vix_exactly_at_deny_threshold_denies(self):
        insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        result, msg = insp.inspect("place_order", {}, {"vix": 50.01})
        assert result == InspectionResult.DENY

    def test_non_numeric_vix_allows(self):
        insp = VolatilityInspector()
        result, msg = insp.inspect("place_order", {}, {"vix": "high"})
        assert result == InspectionResult.ALLOW


# ── RiskInspector ─────────────────────────────────────────────────────────────


class TestRiskInspector:
    def test_missing_proposed_size_allows(self):
        insp = RiskInspector()
        result, msg = insp.inspect("place_order", {}, {"base_size": 1.0})
        assert result == InspectionResult.ALLOW

    def test_missing_base_size_allows(self):
        insp = RiskInspector()
        result, msg = insp.inspect("place_order", {"quantity": 1.0}, {})
        assert result == InspectionResult.ALLOW

    def test_size_within_bounds_allows(self):
        insp = RiskInspector(min_size_mult=0.5, max_size_mult=1.5, max_contracts=2)
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 1.0},
            {"base_size": 1.0, "max_contracts": 2},
        )
        assert result == InspectionResult.ALLOW

    def test_size_exceeds_max_contracts_denies(self):
        insp = RiskInspector(max_contracts=2)
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 3.0},
            {"base_size": 1.0, "max_contracts": 2},
        )
        assert result == InspectionResult.DENY
        assert "max_contracts" in msg

    def test_size_below_lower_bound_denies(self):
        insp = RiskInspector(min_size_mult=0.5, max_size_mult=1.5, max_contracts=10)
        # base=2.0, min=1.0; proposed=0.5 is below lower bound
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 0.5},
            {"base_size": 2.0},
        )
        assert result == InspectionResult.DENY

    def test_size_above_upper_bound_denies(self):
        insp = RiskInspector(min_size_mult=0.5, max_size_mult=1.5, max_contracts=10)
        # base=1.0, max=1.5; proposed=2.0 is above
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 2.0},
            {"base_size": 1.0},
        )
        assert result == InspectionResult.DENY

    def test_zero_proposed_size_allows(self):
        insp = RiskInspector()
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 0.0},
            {"base_size": 1.0},
        )
        assert result == InspectionResult.ALLOW

    def test_proposed_size_via_proposed_size_key(self):
        """Falls back to 'proposed_size' arg key when 'quantity' absent."""
        insp = RiskInspector(min_size_mult=0.5, max_size_mult=1.5, max_contracts=10)
        result, msg = insp.inspect(
            "place_order",
            {"proposed_size": 1.0},
            {"base_size": 1.0},
        )
        assert result == InspectionResult.ALLOW

    def test_context_max_contracts_overrides_default(self):
        insp = RiskInspector(max_contracts=2)
        # context says max=5 so qty=4 should pass the max_contracts check
        result, msg = insp.inspect(
            "place_order",
            {"quantity": 4.0},
            {"base_size": 4.0, "max_contracts": 5},
        )
        # 4 is within [2.0, 6.0] and <= 5
        assert result == InspectionResult.ALLOW


# ── KillSwitchInspector ───────────────────────────────────────────────────────


class TestKillSwitchInspector:
    def test_kill_switch_inactive_allows(self):
        insp = KillSwitchInspector()
        result, msg = insp.inspect("place_order", {}, {"kill_switch_active": False})
        assert result == InspectionResult.ALLOW

    def test_kill_switch_active_denies(self):
        insp = KillSwitchInspector()
        result, msg = insp.inspect("place_order", {}, {"kill_switch_active": True})
        assert result == InspectionResult.DENY
        assert "KillSwitchInspector" in msg
        assert "place_order" in msg

    def test_no_kill_switch_key_allows(self):
        insp = KillSwitchInspector()
        result, msg = insp.inspect("place_order", {}, {})
        assert result == InspectionResult.ALLOW

    def test_truthy_string_denies(self):
        insp = KillSwitchInspector()
        result, msg = insp.inspect("place_order", {}, {"kill_switch_active": "True"})
        assert result == InspectionResult.DENY


# ── ToolInspectionManager ─────────────────────────────────────────────────────


class TestToolInspectionManager:
    def test_empty_inspector_list_allows(self):
        mgr = ToolInspectionManager(inspectors=[])
        result, msgs = mgr.inspect_all("any_tool", {}, {})
        assert result == InspectionResult.ALLOW
        assert msgs == []

    def test_all_allow_returns_allow(self):
        insp1 = LiquidityInspector(min_recent_volume=100.0)
        insp2 = KillSwitchInspector()
        mgr = ToolInspectionManager(inspectors=[insp1, insp2])
        result, msgs = mgr.inspect_all(
            "place_order",
            {},
            {"recent_volume": 5000.0, "kill_switch_active": False},
        )
        assert result == InspectionResult.ALLOW

    def test_one_deny_escalates_to_deny(self):
        insp_allow = LiquidityInspector(min_recent_volume=100.0)
        insp_deny = KillSwitchInspector()
        mgr = ToolInspectionManager(inspectors=[insp_allow, insp_deny])
        result, msgs = mgr.inspect_all(
            "place_order",
            {},
            {"recent_volume": 5000.0, "kill_switch_active": True},
        )
        assert result == InspectionResult.DENY
        assert len(msgs) >= 1

    def test_require_approval_without_deny_returns_require_approval(self):
        insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        mgr = ToolInspectionManager(inspectors=[insp])
        result, msgs = mgr.inspect_all("place_order", {}, {"vix": 40.0})
        assert result == InspectionResult.REQUIRE_APPROVAL
        assert len(msgs) >= 1

    def test_deny_overrides_require_approval(self):
        """DENY has higher priority than REQUIRE_APPROVAL."""
        vol_insp = VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0)
        ks_insp = KillSwitchInspector()
        mgr = ToolInspectionManager(inspectors=[vol_insp, ks_insp])
        # VIX=40 → REQUIRE_APPROVAL; kill_switch=True → DENY
        result, msgs = mgr.inspect_all(
            "place_order",
            {},
            {"vix": 40.0, "kill_switch_active": True},
        )
        assert result == InspectionResult.DENY

    def test_messages_collected_from_all_non_empty(self):
        """Messages from multiple inspectors are all collected."""
        liq = LiquidityInspector(min_recent_volume=1000.0)
        ks = KillSwitchInspector()
        mgr = ToolInspectionManager(inspectors=[liq, ks])
        result, msgs = mgr.inspect_all(
            "place_order",
            {},
            {"recent_volume": 500.0, "kill_switch_active": True},
        )
        assert result == InspectionResult.DENY
        assert len(msgs) == 2  # both inspectors added a message

    def test_empty_messages_not_collected(self):
        """Inspectors that return empty string do not add to messages."""
        liq = LiquidityInspector(min_recent_volume=100.0)
        mgr = ToolInspectionManager(inspectors=[liq])
        result, msgs = mgr.inspect_all(
            "place_order",
            {},
            {"recent_volume": 5000.0},
        )
        assert result == InspectionResult.ALLOW
        assert msgs == []

    def test_inspection_result_priority_ordering(self):
        """Verify DENY > REQUIRE_APPROVAL > ALLOW in the priority map."""
        from risk.tool_inspector import _RESULT_PRIORITY

        assert (
            _RESULT_PRIORITY[InspectionResult.DENY]
            > _RESULT_PRIORITY[InspectionResult.REQUIRE_APPROVAL]
        )
        assert (
            _RESULT_PRIORITY[InspectionResult.REQUIRE_APPROVAL]
            > _RESULT_PRIORITY[InspectionResult.ALLOW]
        )
