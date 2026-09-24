"""Tests for the strategy research-rigor Tier A/B/C gate."""

from __future__ import annotations

from backtest.research_rigor_gate import (
    ResearchGateInput,
    ResearchGateThresholds,
    ResearchTier,
    evaluate_research_gate,
)


def _passing_input(**overrides) -> ResearchGateInput:
    values = {
        "strategy_id": "breakout_opening_range_es_intraday",
        "dsr": 1.15,
        "pbo": 0.20,
        "pf_ci_lower": 1.30,
        "sharpe_degradation": 0.25,
        "oos_trades": 80,
        "regimes_passing": 2,
        "best_regime_dsr": 1.05,
        "max_dd_avg_trade_ratio": 12.0,
        "slippage_2x_dsr": 0.75,
        "permutation_p_value": 0.01,
        "contamination_free": True,
        "dataset_hash": "sha256:bars-v1",
        "parameter_search_trials": 48,
    }
    values.update(overrides)
    return ResearchGateInput(**values)


def test_research_gate_assigns_tier_a_when_all_gates_pass() -> None:
    verdict = evaluate_research_gate(_passing_input())

    assert verdict.tier is ResearchTier.A
    assert verdict.passed is True
    assert verdict.failed_gates == ()
    assert "deflated_sharpe" in verdict.passed_gates


def test_research_gate_assigns_tier_b_for_limited_noncritical_failures() -> None:
    verdict = evaluate_research_gate(
        _passing_input(
            pf_ci_lower=1.05,
            slippage_2x_dsr=0.40,
        )
    )

    assert verdict.tier is ResearchTier.B
    assert verdict.failed_gates == ("pf_ci_lower", "slippage_stress")
    assert len(verdict.improvement_hypotheses) == 2


def test_research_gate_kills_permutation_failure_even_if_only_failure() -> None:
    verdict = evaluate_research_gate(_passing_input(permutation_p_value=0.25))

    assert verdict.tier is ResearchTier.C
    assert verdict.failed_gates == ("permutation_test",)
    assert "permutation_p_value" in verdict.kill_reasons[0]


def test_research_gate_requires_dataset_hash() -> None:
    verdict = evaluate_research_gate(_passing_input(dataset_hash=""))

    assert verdict.tier is ResearchTier.C
    assert verdict.failed_gates == ("dataset_hash",)
    assert verdict.kill_reasons == ("dataset_hash missing",)


def test_research_gate_enforces_parameter_budget() -> None:
    thresholds = ResearchGateThresholds(max_parameter_search_trials=50)

    verdict = evaluate_research_gate(
        _passing_input(parameter_search_trials=75),
        thresholds=thresholds,
    )

    assert verdict.tier is ResearchTier.C
    assert verdict.failed_gates == ("parameter_budget",)
    assert "outside 1..50" in verdict.kill_reasons[0]


def test_research_gate_allows_single_regime_specialist_with_high_dsr() -> None:
    verdict = evaluate_research_gate(
        _passing_input(regimes_passing=1, best_regime_dsr=1.30)
    )

    assert verdict.tier is ResearchTier.A
    assert "regime_breadth" not in verdict.failed_gates

