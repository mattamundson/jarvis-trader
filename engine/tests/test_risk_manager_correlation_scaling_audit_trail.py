"""
Regression test for the correlation-scaling silent-skip bug found by the
2026-08-11 fail-open-safety-checks audit (finding #3).

Before the fix, agents/risk_manager.py:356-369 caught any exception from
PortfolioHedger.get_correlation_scaling_factor() and only logger.debug'd it
-- no hard_checks_detail entry was recorded at all, so a skipped
beta-correlation size-down was invisible in the dashboard pipeline detail
endpoint. The trade still proceeded (this step only ever scales quantity
DOWN, so skipping it is not itself a veto-worthy hard-rule failure, unlike
correlation_exposure), but the skip needs to be visible in the audit trail.
"""

from unittest.mock import MagicMock

import pytest

from agents.risk_manager import RiskManagerAgent


def _make_agent() -> RiskManagerAgent:
    return RiskManagerAgent(llm_client=MagicMock())


def _trade(symbol: str = "MES", quantity: int = 1) -> dict:
    return {
        "action": "buy",
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": 5000.0,
        "limit_price": None,
    }


def _safety() -> dict:
    return {
        "kill_switch_active": False,
        "daily_pnl": 0.0,
        "current_equity": 10_000.0,
    }


def _portfolio() -> dict:
    return {"total_value": 10_000.0, "positions": []}


def test_scaling_factor_exception_recorded_in_audit_trail():
    """A hedger error must appear in hard_checks_detail, not vanish silently."""
    agent = _make_agent()
    agent._hedger.get_correlation_scaling_factor = MagicMock(
        side_effect=RuntimeError("simulated hedger failure")
    )

    veto, checks, modified_qty = agent._hard_rules_check(
        _trade(), _safety(), _portfolio()
    )

    scaling_checks = [c for c in checks if c["check"] == "correlation_scaling"]
    assert scaling_checks, (
        "correlation_scaling check errored but left no hard_checks_detail "
        "entry -- silent-skip regression"
    )
    assert "simulated hedger failure" in scaling_checks[0]["detail"]
    # Sizing-only skip: does not itself veto the trade.
    assert veto is None
    assert modified_qty == 1


def test_scaling_factor_healthy_path_still_passes():
    agent = _make_agent()
    veto, checks, modified_qty = agent._hard_rules_check(
        _trade(), _safety(), _portfolio()
    )

    scaling_checks = [c for c in checks if c["check"] == "correlation_scaling"]
    assert scaling_checks
    assert scaling_checks[0]["passed"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
