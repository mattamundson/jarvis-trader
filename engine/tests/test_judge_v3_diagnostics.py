"""Tests for Judge V3 parameter-stability and feature-ablation diagnostics."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.judge_v3_diagnostics import (
    JudgeDiagnosticError,
    feature_family_ablation,
    parameter_plateau_diagnostic,
)


def test_broad_parameter_plateau_scores_high() -> None:
    rows = []
    for stop in [0.5, 0.75, 1.0]:
        for rvol in [1.2, 1.5, 1.8]:
            distance = abs(stop - 0.75) + abs(rvol - 1.5)
            rows.append({"stop": stop, "rvol": rvol, "score": 1.00 - 0.04 * distance})
    result = parameter_plateau_diagnostic(
        pd.DataFrame(rows),
        parameter_columns=["stop", "rvol"],
        metric_column="score",
        tolerance_fraction=0.10,
    )

    assert result.best_score == pytest.approx(1.0)
    assert result.neighbor_count == 8
    assert result.plateau_score == pytest.approx(1.0)
    assert result.median_relative_drop < 0.10


def test_isolated_parameter_spike_scores_low() -> None:
    rows = []
    for stop in [0.5, 0.75, 1.0]:
        for rvol in [1.2, 1.5, 1.8]:
            score = 2.0 if (stop, rvol) == (0.75, 1.5) else 0.8
            rows.append({"stop": stop, "rvol": rvol, "score": score})
    result = parameter_plateau_diagnostic(
        pd.DataFrame(rows),
        parameter_columns=["stop", "rvol"],
        metric_column="score",
        tolerance_fraction=0.15,
    )

    assert result.best_score == 2.0
    assert result.plateau_score == 0.0
    assert result.median_relative_drop > 0.5


def test_minimize_metric_uses_correct_direction() -> None:
    frame = pd.DataFrame(
        {
            "threshold": [1.0, 2.0, 3.0],
            "loss": [0.22, 0.20, 0.21],
        }
    )
    result = parameter_plateau_diagnostic(
        frame,
        parameter_columns=["threshold"],
        metric_column="loss",
        maximize=False,
        tolerance_fraction=0.15,
    )
    assert result.best_score == 0.20
    assert result.plateau_score == 1.0


def test_feature_ablation_detects_consistent_incremental_value() -> None:
    diagnostics = feature_family_ablation(
        [0.30, 0.25, 0.40, 0.20],
        {
            "relative_strength": [0.20, 0.17, 0.31, 0.12],
            "extra_oscillator": [0.31, 0.25, 0.41, 0.21],
        },
    )
    by_family = {item.family: item for item in diagnostics}

    rs = by_family["relative_strength"]
    assert rs.positive_fold_fraction == 1.0
    assert rs.median_delta > 0

    oscillator = by_family["extra_oscillator"]
    assert oscillator.positive_fold_fraction == 0.0
    assert oscillator.mean_delta < 0


def test_ablation_supports_lower_is_better_loss_metrics() -> None:
    diagnostics = feature_family_ablation(
        [0.20, 0.22, 0.18],
        {"regime": [0.28, 0.29, 0.25]},
        higher_is_better=False,
    )
    diag = diagnostics[0]
    assert diag.positive_fold_fraction == 1.0
    assert diag.mean_delta > 0


def test_diagnostics_fail_closed_on_bad_inputs() -> None:
    with pytest.raises(JudgeDiagnosticError, match="non-empty"):
        parameter_plateau_diagnostic(
            pd.DataFrame(), parameter_columns=["x"], metric_column="score"
        )
    with pytest.raises(JudgeDiagnosticError, match="fold count mismatch"):
        feature_family_ablation([1.0, 2.0], {"bad": [1.0]})
