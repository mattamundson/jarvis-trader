"""Tests for Judge V3 research-only verdict orchestration."""

from __future__ import annotations

from dataclasses import replace

from backtest.judge_v3 import JudgeV3Evidence, JudgeV3Policy, evaluate_judge_v3


def _passing() -> JudgeV3Evidence:
    return JudgeV3Evidence(
        causal_integrity_pass=True,
        parity_pass=True,
        purged_validation_pass=True,
        locked_holdout_pass=True,
        oos_samples=250,
        honest_dsr=0.42,
        dsr_n_trials=54,
        honest_n_trials=54,
        plateau_score=0.80,
        ablation_positive_fold_fraction=0.75,
        cost_stress_pass=True,
        regime_stress_pass=True,
        edge_haircut_pass=True,
    )


def test_all_required_evidence_produces_research_pass_only() -> None:
    verdict = evaluate_judge_v3("candidate-v1", _passing())
    assert verdict.decision == "RESEARCH_PASS"
    assert verdict.passed
    assert verdict.failed_criteria == ()
    assert verdict.missing_criteria == ()


def test_missing_evidence_is_insufficient_not_pass() -> None:
    evidence = replace(_passing(), locked_holdout_pass=None)
    verdict = evaluate_judge_v3("candidate-v1", evidence)
    assert verdict.decision == "INSUFFICIENT_EVIDENCE"
    assert "locked_holdout" in verdict.missing_criteria
    assert not verdict.passed


def test_any_hard_failure_overrides_other_missing_evidence() -> None:
    evidence = replace(_passing(), causal_integrity_pass=False, locked_holdout_pass=None)
    verdict = evaluate_judge_v3("candidate-v1", evidence)
    assert verdict.decision == "RESEARCH_FAIL"
    assert "causal_integrity" in verdict.failed_criteria
    assert "locked_holdout" in verdict.missing_criteria


def test_dsr_using_too_few_campaign_trials_fails() -> None:
    evidence = replace(_passing(), dsr_n_trials=3, honest_n_trials=54)
    verdict = evaluate_judge_v3("candidate-v1", evidence)
    assert verdict.decision == "RESEARCH_FAIL"
    assert "honest_trial_count" in verdict.failed_criteria


def test_isolated_parameter_peak_fails_plateau_gate() -> None:
    evidence = replace(_passing(), plateau_score=0.20)
    verdict = evaluate_judge_v3("candidate-v1", evidence)
    assert verdict.decision == "RESEARCH_FAIL"
    assert "plateau_score" in verdict.failed_criteria


def test_feature_family_that_rarely_adds_value_fails_ablation_gate() -> None:
    evidence = replace(_passing(), ablation_positive_fold_fraction=0.25)
    verdict = evaluate_judge_v3("candidate-v1", evidence)
    assert verdict.decision == "RESEARCH_FAIL"
    assert "ablation_positive_fold_fraction" in verdict.failed_criteria


def test_policy_thresholds_are_explicit_and_configurable() -> None:
    evidence = replace(_passing(), oos_samples=75, honest_dsr=0.08)
    default = evaluate_judge_v3("candidate-v1", evidence)
    assert default.decision == "RESEARCH_FAIL"

    exploratory = JudgeV3Policy(
        min_oos_samples=50,
        min_honest_dsr=0.05,
        min_plateau_score=0.50,
        min_ablation_positive_fold_fraction=0.50,
    )
    relaxed = evaluate_judge_v3("candidate-v1", evidence, policy=exploratory)
    assert relaxed.decision == "RESEARCH_PASS"
