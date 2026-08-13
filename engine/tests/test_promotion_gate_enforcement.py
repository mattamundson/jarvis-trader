"""Tests for the hard pre-trade promotion gate wired into SafetyLayer.check_order.

The promotion gate (``backtest/live_promotion_gate.py``) was previously only a
library + test suite — nothing in the live order path called it, so the enforced
definition-of-done was advisory. This wires it into the single pre-trade chokepoint
(``SafetyLayer.check_order``) in shadow mode: it RECORDS that an un-promoted,
strategy-tagged order would be blocked, and turns that into a hard block only when
``PROMOTION_GATE_ENFORCE`` is set (Amo Tier-3). Default-deny on the promoted set,
which is intentionally empty today (no strategy qualifies).
"""

from __future__ import annotations

import pytest

from backtest import live_promotion_gate as lpg
from risk.safety_layer import OrderRequest, RiskCheckResult, SafetyLayer

# ── env switch ───────────────────────────────────────────────────────────────


def test_promotion_enforce_default_off(monkeypatch):
    monkeypatch.delenv("PROMOTION_GATE_ENFORCE", raising=False)
    assert lpg.promotion_gate_enforced() is False


def test_promotion_enforce_truthy_values(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "on", "On"):
        monkeypatch.setenv("PROMOTION_GATE_ENFORCE", v)
        assert lpg.promotion_gate_enforced() is True, v
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("PROMOTION_GATE_ENFORCE", v)
        assert lpg.promotion_gate_enforced() is False, v


# ── promoted-set membership (default-deny) ───────────────────────────────────


def test_promoted_set_is_empty_by_default():
    # The registry is intentionally empty: no strategy is cleared for live capital.
    assert lpg.PROMOTED_STRATEGIES == frozenset()


def test_is_strategy_promoted_denies_everything_today():
    assert lpg.is_strategy_promoted("MGC_singlefinder_fill_rank1") is False
    assert lpg.is_strategy_promoted("anything") is False


def test_is_strategy_promoted_none_is_never_promoted():
    assert lpg.is_strategy_promoted(None) is False
    assert lpg.is_strategy_promoted("") is False


def test_is_strategy_promoted_honors_populated_set(monkeypatch):
    monkeypatch.setattr(lpg, "PROMOTED_STRATEGIES", frozenset({"PROMOTED_X"}))
    assert lpg.is_strategy_promoted("PROMOTED_X") is True
    assert lpg.is_strategy_promoted("OTHER") is False


# ── SafetyLayer._check_promotion_gate ────────────────────────────────────────


def _sl(mock_settings):
    return SafetyLayer(mock_settings)


def test_untagged_order_passes_shadow_off(mock_settings, monkeypatch):
    monkeypatch.delenv("PROMOTION_GATE_ENFORCE", raising=False)
    order = OrderRequest(symbol="MGC", quantity=1, order_type="market")
    assert _sl(mock_settings)._check_promotion_gate(order).approved is True


def test_untagged_order_passes_even_when_enforced(mock_settings, monkeypatch):
    # Manual/dashboard (untagged) orders are out of this gate's scope.
    monkeypatch.setenv("PROMOTION_GATE_ENFORCE", "1")
    order = OrderRequest(symbol="MGC", quantity=1, order_type="market", strategy_id=None)
    assert _sl(mock_settings)._check_promotion_gate(order).approved is True


def test_tagged_unpromoted_passes_in_shadow_mode(mock_settings, monkeypatch):
    monkeypatch.setenv("PROMOTION_GATE_ENFORCE", "0")
    order = OrderRequest(
        symbol="MGC",
        quantity=1,
        order_type="market",
        strategy_id="MGC_singlefinder_fill_rank1",
    )
    # Shadow mode records but does NOT block.
    assert _sl(mock_settings)._check_promotion_gate(order).approved is True


def test_tagged_unpromoted_blocked_when_enforced(mock_settings, monkeypatch):
    monkeypatch.setenv("PROMOTION_GATE_ENFORCE", "1")
    order = OrderRequest(
        symbol="MGC",
        quantity=1,
        order_type="market",
        strategy_id="MGC_singlefinder_fill_rank1",
    )
    result = _sl(mock_settings)._check_promotion_gate(order)
    assert result.approved is False
    assert "PROMOTION_GATE" in (result.rejection_reason or "")


def test_tagged_promoted_passes_when_enforced(mock_settings, monkeypatch):
    monkeypatch.setenv("PROMOTION_GATE_ENFORCE", "1")
    monkeypatch.setattr(lpg, "PROMOTED_STRATEGIES", frozenset({"MGC_singlefinder_fill_rank1"}))
    order = OrderRequest(
        symbol="MGC",
        quantity=1,
        order_type="market",
        strategy_id="MGC_singlefinder_fill_rank1",
    )
    assert _sl(mock_settings)._check_promotion_gate(order).approved is True


# ── end-to-end: the gate actually fires inside check_order ───────────────────


def test_check_order_blocks_unpromoted_strategy_when_enforced(mock_settings, monkeypatch):
    """Prove the promotion gate is wired into the check_order loop and rejects.

    Earlier checks (kill switch / gating) are stubbed to approve so the rejection
    is unambiguously the promotion gate, not an unrelated pre-trade gate.
    """
    monkeypatch.setenv("PROMOTION_GATE_ENFORCE", "1")
    sl = _sl(mock_settings)
    monkeypatch.setattr(sl, "_check_kill_switch", lambda: RiskCheckResult(approved=True))
    # 2026-07-31: MGC now also carries DO_NOT_TRADE_SYMBOLS membership
    # (backtest/signals.py, honest-data-drain DSR correction) and that check
    # runs even earlier in check_order() than paper_config.enabled below --
    # stub it out too, for the same isolation reason.
    monkeypatch.setattr(sl, "_check_do_not_trade_symbols", lambda order: RiskCheckResult(approved=True))
    # PRB-22 (2026-07-29): MGC now carries paper_config.enabled=False
    # (backtest/paper_config.py) and would be rejected here first, before ever
    # reaching the promotion gate this test exists to isolate — stub it out
    # the same way the two checks above it already are.
    monkeypatch.setattr(sl, "_check_paper_config_enabled", lambda order: RiskCheckResult(approved=True))
    # 2026-08-11: MGC's on-disk gate v2 verdict regressed to FAIL and would be
    # rejected by _check_gate_v2_verdict (2026-08-13) right after the above --
    # stub it out for the same isolation reason.
    monkeypatch.setattr(sl, "_check_gate_v2_verdict", lambda order: RiskCheckResult(approved=True))
    monkeypatch.setattr(sl, "_check_gating_conditions", lambda: RiskCheckResult(approved=True))
    order = OrderRequest(
        symbol="MGC",
        quantity=1,
        order_type="market",
        is_futures=True,
        strategy_id="MGC_trend_rank4",
    )
    result = sl.check_order(order, portfolio_equity=50_000.0)
    assert result.approved is False
    assert "PROMOTION_GATE" in (result.rejection_reason or "")


def test_check_order_does_not_block_unpromoted_in_shadow(mock_settings, monkeypatch):
    """With the flag OFF, a tagged-unpromoted order is NOT blocked by promotion."""
    monkeypatch.delenv("PROMOTION_GATE_ENFORCE", raising=False)
    sl = _sl(mock_settings)
    monkeypatch.setattr(sl, "_check_kill_switch", lambda: RiskCheckResult(approved=True))
    monkeypatch.setattr(sl, "_check_gating_conditions", lambda: RiskCheckResult(approved=True))
    order = OrderRequest(
        symbol="MGC",
        quantity=1,
        order_type="market",
        is_futures=True,
        strategy_id="MGC_trend_rank4",
    )
    result = sl.check_order(order, portfolio_equity=50_000.0)
    # It may pass or be stopped by a LATER risk check, but NOT by the promotion gate.
    assert "PROMOTION_GATE" not in (result.rejection_reason or "")


# ── systematic-strategy promotion path (decision_mode) ───────────────────────


def _all_pass_evidence(**overrides):
    """Evidence with every boolean pillar satisfied; override one to probe it."""
    ev = {
        "strategy_id": "TEST_STRAT",
        "robust_edge": True,
        "per_window_adequate": True,
        "sensitivity_verdict": "ROBUST",
        "leakage_clean": True,
        "cost_robust": True,
        "live_system_stable": True,
        "paper_shadow_passed": True,
        "ensemble_brier": 0.10,
    }
    ev.update(overrides)
    return ev


def test_ensemble_mode_is_default_and_requires_brier():
    # No decision_mode == ensemble mode (unchanged): a missing Brier blocks.
    ev = _all_pass_evidence(ensemble_brier=None)
    res = lpg.evaluate_promotion(ev)
    assert res["criteria"]["ensemble_not_subneutral"] is False
    assert "ensemble_not_subneutral" in res["blocks"]


def test_systematic_mode_waives_ensemble_pillar():
    # A systematic (non-LLM) strategy has no agent ensemble; the pillar is N/A and
    # the OOS power pillars (robust_edge + per_window_adequate) carry the weight.
    ev = _all_pass_evidence(decision_mode="systematic")
    ev.pop("ensemble_brier")  # systematic strategies don't produce one
    res = lpg.evaluate_promotion(ev)
    assert res["criteria"]["ensemble_not_subneutral"] is True
    assert res["promote"] is True


def test_systematic_mode_still_requires_robust_edge():
    # The substitute for the ensemble pillar IS the OOS backtest power, still
    # required — a systematic strategy without a robust edge stays blocked.
    ev = _all_pass_evidence(decision_mode="systematic", robust_edge=False)
    ev.pop("ensemble_brier")
    res = lpg.evaluate_promotion(ev)
    assert res["promote"] is False
    assert "robust_edge" in res["blocks"]


def test_tom_evidence_systematic_no_longer_blocks_on_ensemble():
    res = lpg.evaluate_promotion(lpg.turn_of_month_current_evidence())
    # Systematic path: the ensemble pillar is no longer a blocker...
    assert "ensemble_not_subneutral" not in res["blocks"]
    # ...but TOM is still correctly BLOCKED on the real remaining gaps.
    assert res["promote"] is False
    assert "live_system_stable" in res["blocks"]
    assert "paper_shadow_passed" in res["blocks"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
