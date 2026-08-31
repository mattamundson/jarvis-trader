"""Serializable research report contract for Capital Path forecasts.

This module does not register a live FastAPI route.  It converts validated
research objects into a stable JSON-compatible payload so a later dashboard/API
can consume the same semantics without recomputing or relabeling statistics.
"""

from __future__ import annotations

from typing import Any

from backtest.capital_path_core import CapitalPathConfig
from backtest.capital_path_risk_frontier import RiskPolicyFrontierResult
from backtest.capital_path_scenarios import CapitalPathScenarioSummary


REPORT_SCHEMA_VERSION = 1


def _scenario_payload(summary: CapitalPathScenarioSummary) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, result in summary.results.items():
        ensemble = result.ensemble
        conservative_model_summary = ensemble.model_summaries[ensemble.conservative_model]
        target_time = conservative_model_summary.target_time_conditional
        rows.append(
            {
                "scenario": name,
                "positive_r_multiplier": result.scenario.positive_r_multiplier,
                "success_probability_conservative": ensemble.success_probability_min,
                "success_probability_median_model": ensemble.success_probability_median,
                "success_probability_optimistic": ensemble.success_probability_max,
                "model_spread": ensemble.success_probability_spread,
                "worst_ruin_probability": ensemble.ruin_probability_max,
                "worst_max_drawdown_p95": ensemble.max_drawdown_p95_max,
                "conservative_model": ensemble.conservative_model,
                "optimistic_model": ensemble.optimistic_model,
                "milestone_probabilities_conservative_model": {
                    str(target): probability
                    for target, probability in conservative_model_summary.milestone_probabilities.items()
                },
                "target_time_conditional": (
                    None
                    if target_time is None
                    else {
                        "p05_trades": target_time.p05,
                        "p25_trades": target_time.p25,
                        "median_trades": target_time.median,
                        "p75_trades": target_time.p75,
                        "p95_trades": target_time.p95,
                    }
                ),
            }
        )
    return rows


def _frontier_payload(frontier: RiskPolicyFrontierResult) -> list[dict[str, Any]]:
    return [
        {
            "policy_id": metric.policy_id,
            "pareto_efficient": metric.pareto_efficient,
            "conservative_success_probability": metric.conservative_success_probability,
            "worst_ruin_probability": metric.worst_ruin_probability,
            "worst_max_drawdown_p95": metric.worst_max_drawdown_p95,
            "conservative_scenario": metric.conservative_scenario,
            "conservative_model": metric.conservative_model,
            "median_target_time_conditional_trades": metric.median_target_time_conditional,
        }
        for metric in frontier.metrics
    ]


def build_capital_path_report(
    *,
    config: CapitalPathConfig,
    scenario_summary: CapitalPathScenarioSummary,
    risk_frontier: RiskPolicyFrontierResult,
    evidence_label: str = "RESEARCH_ONLY",
) -> dict[str, Any]:
    """Build a JSON-compatible research report with explicit conditional semantics."""
    if not evidence_label.strip():
        raise ValueError("evidence_label must be non-empty")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "research_only",
        "evidence_label": evidence_label,
        "start_equity": config.start_equity,
        "target_equity": config.target_equity,
        "milestones": list(config.milestones),
        "primary_conservative_scenario": scenario_summary.conservative_scenario,
        "primary_conservative_success_probability": (
            scenario_summary.conservative_success_probability
        ),
        "worst_ruin_probability_across_scenarios": scenario_summary.worst_ruin_probability,
        "worst_max_drawdown_p95_across_scenarios": (
            scenario_summary.worst_max_drawdown_p95
        ),
        "scenario_forecasts": _scenario_payload(scenario_summary),
        "risk_policy_frontier": _frontier_payload(risk_frontier),
        "pareto_policy_ids": list(risk_frontier.pareto_policy_ids),
        "semantics": {
            "target_time": "conditional on modeled success",
            "model_spread": "difference between max and min success probability across configured resampling models; not a confidence interval",
            "edge_haircut": "positive R outcomes are scaled; losses are preserved",
            "authorization": "research output only; no automatic live strategy or risk promotion",
        },
    }
