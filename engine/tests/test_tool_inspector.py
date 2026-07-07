import asyncio

from agents import trader as trader_module
from agents.advisor_client import AdvisorRefinement
from agents.trader import TradeDecision, TraderAgent
from risk.tool_inspector import (
    InspectionResult,
    KillSwitchInspector,
    LiquidityInspector,
    RiskInspector,
    ToolInspectionManager,
    VolatilityInspector,
)
from utils.position_sizing import PositionSizeResult


class DummyLLM:
    api_key = "test-key"


class DummyAdvisor:
    def is_available(self):
        return True

    async def consult_trader_refinement(self, direction, entry, stop, target, confidence, regime, notes=""):
        return AdvisorRefinement(
            entry=entry,
            stop=stop,
            target=target,
            confidence=max(confidence, 0.61),
            notes=f"approved: {notes}",
            consulted=True,
        )


def make_position_size(contracts=1):
    return PositionSizeResult(
        contracts=contracts,
        risk_per_trade=100.0,
        stop_distance=1.0,
        dollar_risk_per_contract=100.0,
        account_value=10000.0,
        symbol="MCL",
        reasoning="fixed fractional sizing",
    )


def make_decision(action="buy", quantity=1, confidence=0.58):
    return TradeDecision(
        symbol="MCL",
        action=action,
        quantity=quantity,
        order_type="market",
        time_in_force="day",
        limit_price=None,
        stop_price=69.5,
        entry_price=70.0,
        target_1=71.0,
        target_2=72.0,
        atr_used=1.0,
        rr_ratio=1.0,
        signal_score=0.7,
        confidence=confidence,
        reasoning="initial trader decision",
        risk_notes="watch crude inventory",
    )


def test_liquidity_inspector_allows_sufficient_volume():
    inspector = LiquidityInspector(min_recent_volume=1000)
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"recent_volume": 2500})
    assert result is InspectionResult.ALLOW
    assert message == ""



def test_liquidity_inspector_denies_thin_volume():
    inspector = LiquidityInspector(min_recent_volume=1000)
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"recent_volume": 400})
    assert result is InspectionResult.DENY
    assert "recent_volume=400.00" in message



def test_volatility_inspector_allows_normal_vix():
    inspector = VolatilityInspector()
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"vix": 22})
    assert result is InspectionResult.ALLOW
    assert message == ""



def test_volatility_inspector_requires_approval_for_vix_40():
    inspector = VolatilityInspector()
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"vix": 40})
    assert result is InspectionResult.REQUIRE_APPROVAL
    assert "VIX=40.00" in message



def test_volatility_inspector_denies_extreme_vix():
    inspector = VolatilityInspector()
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"vix": 55})
    assert result is InspectionResult.DENY
    assert "deny threshold" in message



def test_risk_inspector_denies_out_of_bounds_size():
    inspector = RiskInspector(max_contracts=2)
    result, message = inspector.inspect("ib_order", {"quantity": 3}, {"base_size": 1, "max_contracts": 2})
    assert result is InspectionResult.DENY
    assert "max_contracts=2" in message



def test_kill_switch_inspector_denies_when_active():
    inspector = KillSwitchInspector()
    result, message = inspector.inspect("ib_order", {"quantity": 1}, {"kill_switch_active": True})
    assert result is InspectionResult.DENY
    assert "kill_switch_active=True" in message



def test_manager_returns_most_restrictive_result():
    manager = ToolInspectionManager([
        LiquidityInspector(min_recent_volume=1000),
        VolatilityInspector(),
        KillSwitchInspector(),
    ])
    result, messages = manager.inspect_all(
        "ib_order",
        {"quantity": 1},
        {"recent_volume": 500, "vix": 40, "kill_switch_active": False},
    )
    assert result is InspectionResult.DENY
    assert any("LiquidityInspector denied" in message for message in messages)
    assert any("requires approval" in message for message in messages)



def test_trader_apply_tool_inspection_uses_advisor_for_vix_40(monkeypatch):
    agent = TraderAgent(DummyLLM())
    decision = make_decision()
    position_size = make_position_size(contracts=1)
    analyst_reports = {
        "fundamental": {"key_metrics": {"vix": 40}},
        "technical": {},
    }
    safety_status = {"kill_switch_active": False}

    monkeypatch.setattr(trader_module, "_get_advisor", lambda: DummyAdvisor())

    updated_decision, used_advisor = asyncio.run(
        agent._apply_tool_inspection(
            symbol="MCL",
            decision=decision,
            analyst_reports=analyst_reports,
            safety_status=safety_status,
            position_size=position_size,
        )
    )

    assert used_advisor is True
    assert updated_decision.action == "buy"
    assert "[Tool Inspection]" in updated_decision.reasoning
    assert "[Advisor Approval]" in updated_decision.reasoning
    assert updated_decision.confidence >= 0.61
