"""Fail-closed Judge V3 research verdict orchestration.

Judge V3 is a *research promotion* gate only. A PASS means a candidate has earned
the right to continue research/paper-shadow evaluation. It never authorizes live
trading, changes risk limits, or modifies broker state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


JudgeDecision = Literal["RESEARCH_PASS", "RESEARCH_FAIL", "INSUFFICIENT_EVIDENCE"]


@dataclass(frozen=True)
class JudgeV3Policy:
    min_oos_samples: int = 100
    min_honest_dsr: float = 0.10
    min_plateau_score: float = 0.60
    min_ablation_positive_fold_fraction: float = 0.60

    def __post_init__(self) -> None:
        if self.min_oos_samples < 1:
            raise ValueError("min_oos_samples must be >= 1")
        for name in (
            "min_honest_dsr",
            "min_plateau_score",
            "min_ablation_positive_fold_fraction",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1]")


@dataclass(frozen=True)
class JudgeV3Evidence:
    causal_integrity_pass: bool | None
    parity_pass: bool | None
    purged_validation_pass: bool | None
    locked_holdout_pass: bool | None
    oos_samples: int | None
    honest_dsr: float | None
    dsr_n_trials: int | None
    honest_n_trials: int | None
    plateau_score: float | None
    ablation_positive_fold_fraction: float | None
    cost_stress_pass: bool | None
    regime_stress_pass: bool | None
    edge_haircut_pass: bool | None


@dataclass(frozen=True)
class JudgeCriterion:
    name: str
    status: Literal["PASS", "FAIL", "MISSING"]
    value: Any
    requirement: str
    reason: str


@dataclass(frozen=True)
class JudgeV3Verdict:
    strategy_id: str
    decision: JudgeDecision
    criteria: tuple[JudgeCriterion, ...]

    @property
    def passed(self) -> bool:
        return self.decision == "RESEARCH_PASS"

    @property
    def failed_criteria(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.criteria if item.status == "FAIL")

    @property
    def missing_criteria(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.criteria if item.status == "MISSING")


def _boolean_criterion(name: str, value: bool | None, requirement: str) -> JudgeCriterion:
    if value is None:
        return JudgeCriterion(name, "MISSING", None, requirement, "evidence not supplied")
    if value:
        return JudgeCriterion(name, "PASS", True, requirement, "requirement satisfied")
    return JudgeCriterion(name, "FAIL", False, requirement, "requirement not satisfied")


def _minimum_criterion(
    name: str,
    value: float | int | None,
    minimum: float | int,
) -> JudgeCriterion:
    requirement = f">= {minimum}"
    if value is None:
        return JudgeCriterion(name, "MISSING", None, requirement, "evidence not supplied")
    if value >= minimum:
        return JudgeCriterion(name, "PASS", value, requirement, "minimum satisfied")
    return JudgeCriterion(name, "FAIL", value, requirement, "below required minimum")


def evaluate_judge_v3(
    strategy_id: str,
    evidence: JudgeV3Evidence,
    *,
    policy: JudgeV3Policy | None = None,
) -> JudgeV3Verdict:
    """Evaluate one candidate against explicit fail-closed research criteria."""
    if not strategy_id.strip():
        raise ValueError("strategy_id must be non-empty")
    p = policy or JudgeV3Policy()

    criteria: list[JudgeCriterion] = [
        _boolean_criterion("causal_integrity", evidence.causal_integrity_pass, "must pass"),
        _boolean_criterion("source_parity", evidence.parity_pass, "must pass"),
        _boolean_criterion(
            "purged_validation", evidence.purged_validation_pass, "purged/embargo validation must pass"
        ),
        _boolean_criterion("locked_holdout", evidence.locked_holdout_pass, "must pass"),
        _minimum_criterion("oos_samples", evidence.oos_samples, p.min_oos_samples),
        _minimum_criterion("honest_dsr", evidence.honest_dsr, p.min_honest_dsr),
        _minimum_criterion("plateau_score", evidence.plateau_score, p.min_plateau_score),
        _minimum_criterion(
            "ablation_positive_fold_fraction",
            evidence.ablation_positive_fold_fraction,
            p.min_ablation_positive_fold_fraction,
        ),
        _boolean_criterion("cost_stress", evidence.cost_stress_pass, "must pass"),
        _boolean_criterion("regime_stress", evidence.regime_stress_pass, "must pass"),
        _boolean_criterion("edge_haircut", evidence.edge_haircut_pass, "must pass"),
    ]

    if evidence.dsr_n_trials is None or evidence.honest_n_trials is None:
        criteria.append(
            JudgeCriterion(
                "honest_trial_count",
                "MISSING",
                {"dsr_n_trials": evidence.dsr_n_trials, "honest_n_trials": evidence.honest_n_trials},
                "DSR must use n_trials >= honest preregistered campaign count",
                "trial-count evidence incomplete",
            )
        )
    elif evidence.dsr_n_trials < evidence.honest_n_trials:
        criteria.append(
            JudgeCriterion(
                "honest_trial_count",
                "FAIL",
                {"dsr_n_trials": evidence.dsr_n_trials, "honest_n_trials": evidence.honest_n_trials},
                "DSR must use n_trials >= honest preregistered campaign count",
                "DSR was deflated using too few research trials",
            )
        )
    else:
        criteria.append(
            JudgeCriterion(
                "honest_trial_count",
                "PASS",
                {"dsr_n_trials": evidence.dsr_n_trials, "honest_n_trials": evidence.honest_n_trials},
                "DSR must use n_trials >= honest preregistered campaign count",
                "trial-count deflation is not understated",
            )
        )

    if any(item.status == "FAIL" for item in criteria):
        decision: JudgeDecision = "RESEARCH_FAIL"
    elif any(item.status == "MISSING" for item in criteria):
        decision = "INSUFFICIENT_EVIDENCE"
    else:
        decision = "RESEARCH_PASS"

    return JudgeV3Verdict(strategy_id=strategy_id, decision=decision, criteria=tuple(criteria))
