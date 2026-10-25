"""Research-rigor gate for strategy funnel tiering.

This module is intentionally pure: callers pass already-computed backtest,
robustness, and provenance metrics; the gate only classifies and explains.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ResearchTier(str, Enum):
    """Strategy funnel tier assigned by the research-rigor gate."""

    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class ResearchGateThresholds:
    """Moderately aggressive robustness thresholds for Tier A candidates."""

    min_dsr: float = 0.80
    max_pbo: float = 0.40
    min_pf_ci_lower: float = 1.15
    max_sharpe_degradation: float = 0.40
    min_oos_trades: int = 40
    min_regimes_passing: int = 2
    min_specialist_regime_dsr: float = 1.20
    max_dd_avg_trade_ratio: float = 25.0
    min_2x_slippage_dsr: float = 0.50
    max_permutation_p_value: float = 0.05
    max_parameter_search_trials: int = 200


@dataclass(frozen=True)
class ResearchGateInput:
    """Precomputed metrics required to classify one strategy hypothesis."""

    strategy_id: str
    dsr: float
    pbo: float
    pf_ci_lower: float
    sharpe_degradation: float
    oos_trades: int
    regimes_passing: int
    best_regime_dsr: float
    max_dd_avg_trade_ratio: float
    slippage_2x_dsr: float
    permutation_p_value: float
    contamination_free: bool
    dataset_hash: str
    parameter_search_trials: int
    parameter_search_budget: int | None = None
    metadata: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class ResearchGateVerdict:
    """Explainable Tier A/B/C verdict."""

    strategy_id: str
    tier: ResearchTier
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    kill_reasons: tuple[str, ...]
    improvement_hypotheses: tuple[str, ...]
    metrics: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.tier is ResearchTier.A


def evaluate_research_gate(
    item: ResearchGateInput,
    *,
    thresholds: ResearchGateThresholds | None = None,
) -> ResearchGateVerdict:
    """Classify one strategy as Tier A/B/C from already-computed metrics."""
    thresholds = thresholds or ResearchGateThresholds()
    budget = item.parameter_search_budget or thresholds.max_parameter_search_trials
    gate_results = {
        "deflated_sharpe": item.dsr >= thresholds.min_dsr,
        "pbo": item.pbo < thresholds.max_pbo,
        "pf_ci_lower": item.pf_ci_lower > thresholds.min_pf_ci_lower,
        "sharpe_degradation": item.sharpe_degradation < thresholds.max_sharpe_degradation,
        "oos_trade_count": item.oos_trades >= thresholds.min_oos_trades,
        "regime_breadth": (
            item.regimes_passing >= thresholds.min_regimes_passing
            or item.best_regime_dsr >= thresholds.min_specialist_regime_dsr
        ),
        "drawdown_to_avg_trade": item.max_dd_avg_trade_ratio < thresholds.max_dd_avg_trade_ratio,
        "slippage_stress": item.slippage_2x_dsr >= thresholds.min_2x_slippage_dsr,
        "permutation_test": item.permutation_p_value < thresholds.max_permutation_p_value,
        "bar_contamination": bool(item.contamination_free),
        "dataset_hash": bool(item.dataset_hash.strip()),
        "parameter_budget": 0 < item.parameter_search_trials <= budget,
    }
    passed = tuple(name for name, ok in gate_results.items() if ok)
    failed = tuple(name for name, ok in gate_results.items() if not ok)
    critical_failures = {
        "permutation_test",
        "bar_contamination",
        "dataset_hash",
        "parameter_budget",
    }

    if not failed:
        tier = ResearchTier.A
    elif len(failed) <= 2 and item.dsr >= 1.0 and not (critical_failures & set(failed)):
        tier = ResearchTier.B
    else:
        tier = ResearchTier.C

    kill_reasons = tuple(_kill_reason(name, item, thresholds, budget) for name in failed)
    return ResearchGateVerdict(
        strategy_id=item.strategy_id,
        tier=tier,
        passed_gates=passed,
        failed_gates=failed,
        kill_reasons=kill_reasons,
        improvement_hypotheses=tuple(_improvement_hypothesis(name) for name in failed),
        metrics={
            "dsr": item.dsr,
            "pbo": item.pbo,
            "pf_ci_lower": item.pf_ci_lower,
            "sharpe_degradation": item.sharpe_degradation,
            "oos_trades": item.oos_trades,
            "regimes_passing": item.regimes_passing,
            "best_regime_dsr": item.best_regime_dsr,
            "max_dd_avg_trade_ratio": item.max_dd_avg_trade_ratio,
            "slippage_2x_dsr": item.slippage_2x_dsr,
            "permutation_p_value": item.permutation_p_value,
            "contamination_free": item.contamination_free,
            "dataset_hash": item.dataset_hash,
            "parameter_search_trials": item.parameter_search_trials,
            "parameter_search_budget": budget,
        },
    )


def _kill_reason(
    gate: str,
    item: ResearchGateInput,
    thresholds: ResearchGateThresholds,
    budget: int,
) -> str:
    reasons = {
        "deflated_sharpe": f"dsr {item.dsr:.3f} < {thresholds.min_dsr:.3f}",
        "pbo": f"pbo {item.pbo:.3f} >= {thresholds.max_pbo:.3f}",
        "pf_ci_lower": f"pf_ci_lower {item.pf_ci_lower:.3f} <= {thresholds.min_pf_ci_lower:.3f}",
        "sharpe_degradation": (
            f"sharpe_degradation {item.sharpe_degradation:.3f} "
            f">= {thresholds.max_sharpe_degradation:.3f}"
        ),
        "oos_trade_count": f"oos_trades {item.oos_trades} < {thresholds.min_oos_trades}",
        "regime_breadth": (
            f"regimes_passing {item.regimes_passing} < {thresholds.min_regimes_passing} "
            f"and best_regime_dsr {item.best_regime_dsr:.3f} "
            f"< {thresholds.min_specialist_regime_dsr:.3f}"
        ),
        "drawdown_to_avg_trade": (
            f"max_dd_avg_trade_ratio {item.max_dd_avg_trade_ratio:.3f} "
            f">= {thresholds.max_dd_avg_trade_ratio:.3f}"
        ),
        "slippage_stress": (
            f"slippage_2x_dsr {item.slippage_2x_dsr:.3f} "
            f"< {thresholds.min_2x_slippage_dsr:.3f}"
        ),
        "permutation_test": (
            f"permutation_p_value {item.permutation_p_value:.3f} "
            f">= {thresholds.max_permutation_p_value:.3f}"
        ),
        "bar_contamination": "bar contamination check failed",
        "dataset_hash": "dataset_hash missing",
        "parameter_budget": (
            f"parameter_search_trials {item.parameter_search_trials} outside 1..{budget}"
        ),
    }
    return reasons[gate]


def _improvement_hypothesis(gate: str) -> str:
    hypotheses = {
        "deflated_sharpe": "Reduce family trials or improve OOS return stability before retest.",
        "pbo": "Reduce parameter degrees of freedom and rerun CPCV rank stability.",
        "pf_ci_lower": "Improve payoff asymmetry or reduce cost sensitivity before promotion.",
        "sharpe_degradation": "Constrain parameters to values stable across IS/OOS windows.",
        "oos_trade_count": "Use a longer validation sample or reclassify as a lower-frequency strategy.",
        "regime_breadth": "Add a regime filter tied to the observed edge regime.",
        "drawdown_to_avg_trade": "Cut tail exposure or add a drawdown-aware stop/risk overlay.",
        "slippage_stress": "Move entries to more liquid windows or require wider expected edge.",
        "permutation_test": "Re-check signal construction for bar-sequence overfit.",
        "bar_contamination": "Repair/rebuild the underlying bar dataset before any retest.",
        "dataset_hash": "Write dataset hash into the result artifact before tiering.",
        "parameter_budget": "Cap or pre-register the parameter search before rerunning.",
    }
    return hypotheses[gate]
