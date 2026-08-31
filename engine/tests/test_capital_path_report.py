"""Tests for the Capital Path research report contract."""

from __future__ import annotations

import json

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import MonteCarloSpec
from backtest.capital_path_report import build_capital_path_report
from backtest.capital_path_risk_frontier import (
    RiskPolicyCandidate,
    evaluate_risk_policy_frontier,
)
from backtest.capital_path_scenarios import EdgeScenario, run_edge_scenarios


def _models() -> dict[str, MonteCarloSpec]:
    return {
        "iid": MonteCarloSpec(
            n_paths=80, trades_per_path=30, seed=31, resampling_method="iid"
        ),
        "moving": MonteCarloSpec(
            n_paths=80,
            trades_per_path=30,
            seed=31,
            resampling_method="moving_block",
            block_size=2,
        ),
    }


def test_report_is_json_serializable_and_explicit_about_semantics() -> None:
    empirical = [-1.0, -0.5, 0.5, 1.0, 2.0, 3.0]
    config = CapitalPathConfig(
        start_equity=100.0,
        target_equity=150.0,
        milestones=(120.0, 150.0),
        ruin_drawdown=0.35,
    )
    scenarios = (EdgeScenario("full", 1.0), EdgeScenario("half", 0.5))
    scenario_summary = run_edge_scenarios(
        empirical,
        scenarios=scenarios,
        model_specs=_models(),
        config=config,
        risk_policy=RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None),
    )
    frontier = evaluate_risk_policy_frontier(
        empirical,
        policies=(
            RiskPolicyCandidate(
                "p3",
                RiskPolicy(base_risk_fraction=0.03, drawdown_bands=(), halt_drawdown=None),
            ),
            RiskPolicyCandidate(
                "p5",
                RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None),
            ),
        ),
        scenarios=scenarios,
        model_specs=_models(),
        config=config,
    )
    report = build_capital_path_report(
        config=config,
        scenario_summary=scenario_summary,
        risk_frontier=frontier,
        evidence_label="SYNTHETIC_TEST",
    )

    encoded = json.dumps(report, sort_keys=True)
    assert encoded
    assert report["status"] == "research_only"
    assert report["evidence_label"] == "SYNTHETIC_TEST"
    assert report["start_equity"] == 100.0
    assert report["target_equity"] == 150.0
    assert report["semantics"]["target_time"] == "conditional on modeled success"
    assert "not a confidence interval" in report["semantics"]["model_spread"]
    assert report["pareto_policy_ids"]
    assert len(report["scenario_forecasts"]) == 2


def test_blank_evidence_label_fails_closed() -> None:
    empirical = [-1.0, 1.0, 2.0]
    config = CapitalPathConfig(
        start_equity=100.0,
        target_equity=150.0,
        milestones=(150.0,),
        ruin_drawdown=0.35,
    )
    scenarios = (EdgeScenario("full", 1.0),)
    models = _models()
    scenario_summary = run_edge_scenarios(
        empirical,
        scenarios=scenarios,
        model_specs=models,
        config=config,
        risk_policy=RiskPolicy(base_risk_fraction=0.05),
    )
    frontier = evaluate_risk_policy_frontier(
        empirical,
        policies=(
            RiskPolicyCandidate("a", RiskPolicy(base_risk_fraction=0.03)),
            RiskPolicyCandidate("b", RiskPolicy(base_risk_fraction=0.05)),
        ),
        scenarios=scenarios,
        model_specs=models,
        config=config,
    )
    try:
        build_capital_path_report(
            config=config,
            scenario_summary=scenario_summary,
            risk_frontier=frontier,
            evidence_label="  ",
        )
    except ValueError as exc:
        assert "evidence_label" in str(exc)
    else:
        raise AssertionError("blank evidence label must fail closed")
