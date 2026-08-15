"""Tests for the live-capital promotion gate (Task 10).

The promotion gate is the ENFORCED definition-of-done: the single hard check the
live-wiring must call before any candidate is allowed to risk real capital. It
turns the prose DoD into code so a candidate cannot be promoted while any pillar
is unmet — including a sub-neutral agent ensemble (Brier > 0.25), which is a hard
block regardless of backtest quality.
"""

from __future__ import annotations

import pytest

from backtest import live_promotion_gate as G


def _full_pass() -> dict:
    """Evidence where every pillar is satisfied."""
    return {
        "strategy_id": "MGC_singlefinder_fill_rank1",
        "robust_edge": True,
        "per_window_adequate": True,
        "sensitivity_verdict": "ROBUST",
        "leakage_clean": True,
        "cost_robust": True,
        "live_system_stable": True,
        "ensemble_brier": 0.18,
        "paper_shadow_passed": True,
    }


def test_full_pass_promotes():
    res = G.evaluate_promotion(_full_pass())
    assert res["promote"] is True
    assert res["blocks"] == []


def test_robust_edge_false_blocks():
    ev = _full_pass()
    ev["robust_edge"] = False
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "robust_edge" in res["blocks"]


def test_subneutral_ensemble_is_hard_block():
    # Everything else perfect, but a worse-than-random ensemble cannot authorize.
    ev = _full_pass()
    ev["ensemble_brier"] = 0.42
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "ensemble_not_subneutral" in res["blocks"]


def test_unknown_ensemble_brier_blocks_failsafe():
    ev = _full_pass()
    ev["ensemble_brier"] = None
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "ensemble_not_subneutral" in res["blocks"]


def test_bool_ensemble_brier_blocks_failsafe():
    # bool is an int subclass in Python: False<ENSEMBLE_BRIER_CEILING is 0<0.25 (True).
    # Without an explicit bool exclusion this pillar would wrongly PASS on
    # ensemble_brier=False, contradicting the module's own default-deny invariant
    # ("any pillar that is absent, None, or False blocks").
    ev = _full_pass()
    ev["ensemble_brier"] = False
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "ensemble_not_subneutral" in res["blocks"]


def test_brier_exactly_at_ceiling_blocks():
    # 0.25 is the neutral baseline (predict 0.5 always); the edge must BEAT it.
    ev = _full_pass()
    ev["ensemble_brier"] = G.ENSEMBLE_BRIER_CEILING
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "ensemble_not_subneutral" in res["blocks"]


def test_fragile_sensitivity_blocks():
    ev = _full_pass()
    ev["sensitivity_verdict"] = "FRAGILE"
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "sensitivity_robust" in res["blocks"]


def test_acceptable_sensitivity_allowed():
    ev = _full_pass()
    ev["sensitivity_verdict"] = "ACCEPTABLE"
    res = G.evaluate_promotion(ev)
    # ACCEPTABLE clears the sensitivity pillar (only FRAGILE blocks).
    assert "sensitivity_robust" not in res["blocks"]


def test_missing_pillar_blocks_failsafe():
    # An absent boolean pillar is treated as not-satisfied (default-deny).
    ev = _full_pass()
    del ev["leakage_clean"]
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "leakage_clean" in res["blocks"]


def test_multiple_blocks_all_reported():
    ev = _full_pass()
    ev["robust_edge"] = False
    ev["live_system_stable"] = False
    ev["ensemble_brier"] = 0.5
    res = G.evaluate_promotion(ev)
    assert res["promote"] is False
    assert {"robust_edge", "live_system_stable", "ensemble_not_subneutral"} <= set(res["blocks"])


def test_singlefinder_current_state_is_blocked():
    # The real candidate today: survives sensitivity/cost/leakage but NOT robust
    # (needs more independent windows) and the live ensemble is sub-neutral.
    res = G.evaluate_promotion(G.singlefinder_current_evidence())
    assert res["promote"] is False
    assert "robust_edge" in res["blocks"]
    assert "ensemble_not_subneutral" in res["blocks"]


def test_report_is_readable():
    res = G.evaluate_promotion(_full_pass())
    txt = G.format_promotion_report(res)
    assert "PROMOTE" in txt
    assert "MGC_singlefinder_fill_rank1" in txt


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
