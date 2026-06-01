from __future__ import annotations

from enum import Enum
from typing import Protocol


class InspectionResult(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ToolInspector(Protocol):
    def inspect(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, str]:
        ...


_RESULT_PRIORITY = {
    InspectionResult.ALLOW: 0,
    InspectionResult.REQUIRE_APPROVAL: 1,
    InspectionResult.DENY: 2,
}


class ToolInspectionManager:
    def __init__(self, inspectors: list[ToolInspector]):
        self.inspectors = inspectors

    def inspect_all(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, list[str]]:
        final_result = InspectionResult.ALLOW
        messages: list[str] = []

        for inspector in self.inspectors:
            result, message = inspector.inspect(tool_name, args, context)
            if message:
                messages.append(message)
            if _RESULT_PRIORITY[result] > _RESULT_PRIORITY[final_result]:
                final_result = result

        return final_result, messages


class LiquidityInspector:
    def __init__(self, min_recent_volume: float = 1000.0):
        self.min_recent_volume = float(min_recent_volume)

    def inspect(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, str]:
        recent_volume = context.get("recent_volume")
        if recent_volume is None:
            return InspectionResult.ALLOW, ""

        try:
            recent_volume = float(recent_volume)
        except (TypeError, ValueError):
            return InspectionResult.ALLOW, ""

        if recent_volume < self.min_recent_volume:
            return (
                InspectionResult.DENY,
                f"LiquidityInspector denied {tool_name}: recent_volume={recent_volume:.2f} below threshold {self.min_recent_volume:.2f}",
            )
        return InspectionResult.ALLOW, ""


class VolatilityInspector:
    def __init__(self, require_approval_vix: float = 35.0, deny_vix: float = 50.0):
        self.require_approval_vix = float(require_approval_vix)
        self.deny_vix = float(deny_vix)

    def inspect(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, str]:
        vix = context.get("vix")
        if vix is None:
            return InspectionResult.ALLOW, ""

        try:
            vix = float(vix)
        except (TypeError, ValueError):
            return InspectionResult.ALLOW, ""

        if vix > self.deny_vix:
            return (
                InspectionResult.DENY,
                f"VolatilityInspector denied {tool_name}: VIX={vix:.2f} exceeds deny threshold {self.deny_vix:.2f}",
            )
        if vix > self.require_approval_vix:
            return (
                InspectionResult.REQUIRE_APPROVAL,
                f"VolatilityInspector requires approval for {tool_name}: VIX={vix:.2f} exceeds approval threshold {self.require_approval_vix:.2f}",
            )
        return InspectionResult.ALLOW, ""


class RiskInspector:
    def __init__(
        self,
        min_size_mult: float = 0.5,
        max_size_mult: float = 1.5,
        max_contracts: int = 2,
    ):
        self.min_size_mult = float(min_size_mult)
        self.max_size_mult = float(max_size_mult)
        self.max_contracts = int(max_contracts)

    def inspect(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, str]:
        proposed_size = args.get("quantity", args.get("proposed_size"))
        base_size = context.get("base_size")
        max_contracts = int(context.get("max_contracts", self.max_contracts))

        if proposed_size in (None, "") or base_size in (None, ""):
            return InspectionResult.ALLOW, ""

        try:
            proposed_size = float(proposed_size)
            base_size = float(base_size)
        except (TypeError, ValueError):
            return InspectionResult.ALLOW, ""

        if proposed_size <= 0 or base_size <= 0:
            return InspectionResult.ALLOW, ""

        low_bound = base_size * self.min_size_mult
        high_bound = base_size * self.max_size_mult

        if proposed_size > max_contracts:
            return (
                InspectionResult.DENY,
                f"RiskInspector denied {tool_name}: proposed_size={proposed_size:.2f} exceeds max_contracts={max_contracts}",
            )
        if proposed_size < low_bound or proposed_size > high_bound:
            return (
                InspectionResult.DENY,
                f"RiskInspector denied {tool_name}: proposed_size={proposed_size:.2f} outside allowed range [{low_bound:.2f}, {high_bound:.2f}] from base_size={base_size:.2f}",
            )
        return InspectionResult.ALLOW, ""


class KillSwitchInspector:
    def inspect(self, tool_name: str, args: dict, context: dict) -> tuple[InspectionResult, str]:
        if bool(context.get("kill_switch_active", False)):
            return (
                InspectionResult.DENY,
                f"KillSwitchInspector denied {tool_name}: kill_switch_active=True",
            )
        return InspectionResult.ALLOW, ""
