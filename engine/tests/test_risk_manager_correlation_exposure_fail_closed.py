"""
Regression test for the correlation-exposure fail-open bug found by the
2026-08-11 fail-open-safety-checks audit.

Before the fix, agents/risk_manager.py:396-398 caught any exception from
CorrelationMonitor.is_overexposed() and converted it straight to _pass(),
silently approving a trade the exposure check never actually evaluated.
_hard_rules_check()'s own docstring says a hard rule failure must veto the
trade immediately -- an errored check is not the same as a passed check.
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


def test_correlation_monitor_exception_vetoes_trade(monkeypatch):
    """A CorrelationMonitor error must fail CLOSED (veto), not silently pass."""
    import agents.risk_manager as rm

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated CorrelationMonitor failure")

    monkeypatch.setattr(rm, "CorrelationMonitor", _boom)

    agent = _make_agent()
    veto, checks, modified_qty = agent._hard_rules_check(
        _trade(), _safety(), _portfolio()
    )

    assert veto is not None, (
        "correlation_exposure check errored but the trade was not vetoed -- "
        "fail-open regression"
    )
    assert modified_qty == 0
    exposure_check = next(c for c in checks if c["check"] == "correlation_exposure")
    assert exposure_check["passed"] is False


def test_correlation_monitor_healthy_path_still_passes():
    """Sanity check: a normal, non-overexposed portfolio still passes."""
    agent = _make_agent()
    veto, checks, modified_qty = agent._hard_rules_check(
        _trade(), _safety(), _portfolio()
    )

    exposure_check = next(c for c in checks if c["check"] == "correlation_exposure")
    assert exposure_check["passed"] is True
    assert veto is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
