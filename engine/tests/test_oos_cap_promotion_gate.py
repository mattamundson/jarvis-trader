"""Tests for the dormant OOS-contamination cap wired into the promotion gate.

The cap must be DORMANT by default (env unset) — promotion behavior unchanged —
and only block when OOS_CAP_ENFORCE is on AND the quarter's OOS budget is
exhausted. Fail-closed when enforced but the ledger is unreadable.
"""
from types import SimpleNamespace

import backtest.live_promotion_gate as gate


def _passing_evidence() -> dict:
    """Evidence where every existing pillar passes (promote would be True)."""
    return {
        "strategy_id": "X",
        "robust_edge": True,
        "per_window_adequate": True,
        "leakage_clean": True,
        "cost_robust": True,
        "live_system_stable": True,
        "paper_shadow_passed": True,
        "sensitivity_verdict": "ROBUST",
        "ensemble_brier": 0.1,
    }


class TestOosCapFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("OOS_CAP_ENFORCE", raising=False)
        assert gate.oos_cap_enforced() is False

    def test_on_when_truthy(self, monkeypatch):
        monkeypatch.setenv("OOS_CAP_ENFORCE", "1")
        assert gate.oos_cap_enforced() is True


class TestDormantByDefault:
    def test_pillar_present_and_true(self, monkeypatch):
        monkeypatch.setattr(gate, "oos_cap_enforced", lambda: False)
        result = gate.evaluate_promotion(_passing_evidence())
        assert result["criteria"]["oos_budget_ok"] is True
        assert result["promote"] is True  # dormant -> unchanged

    def test_does_not_read_ledger_when_off(self, monkeypatch):
        monkeypatch.setattr(gate, "oos_cap_enforced", lambda: False)
        called = {"n": 0}

        def boom():
            called["n"] += 1
            raise AssertionError("ledger must not be read when dormant")

        monkeypatch.setattr(
            "analytics.oos_access_ledger.budget_status", lambda **kw: boom()
        )
        gate.evaluate_promotion(_passing_evidence())
        assert called["n"] == 0


class TestEnforced:
    def test_budget_exhausted_blocks(self, monkeypatch):
        monkeypatch.setattr(gate, "oos_cap_enforced", lambda: True)
        monkeypatch.setattr(
            "analytics.oos_access_ledger.budget_status",
            lambda **kw: SimpleNamespace(exceeded=True),
        )
        result = gate.evaluate_promotion(_passing_evidence())
        assert result["criteria"]["oos_budget_ok"] is False
        assert "oos_budget_ok" in result["blocks"]
        assert result["promote"] is False

    def test_budget_available_allows(self, monkeypatch):
        monkeypatch.setattr(gate, "oos_cap_enforced", lambda: True)
        monkeypatch.setattr(
            "analytics.oos_access_ledger.budget_status",
            lambda **kw: SimpleNamespace(exceeded=False),
        )
        result = gate.evaluate_promotion(_passing_evidence())
        assert result["criteria"]["oos_budget_ok"] is True
        assert result["promote"] is True

    def test_unreadable_ledger_fails_closed(self, monkeypatch):
        monkeypatch.setattr(gate, "oos_cap_enforced", lambda: True)

        def _raise(**kw):
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr("analytics.oos_access_ledger.budget_status", _raise)
        result = gate.evaluate_promotion(_passing_evidence())
        assert result["criteria"]["oos_budget_ok"] is False  # fail-closed
        assert result["promote"] is False
