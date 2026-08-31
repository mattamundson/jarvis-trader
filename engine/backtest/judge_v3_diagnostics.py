"""Judge V3 diagnostics for parameter stability and incremental feature value.

These helpers are descriptive validation primitives. They do not select or
promote strategies. Their purpose is to penalize isolated parameter peaks and
measure whether a feature family adds value across matched validation folds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


class JudgeDiagnosticError(ValueError):
    """Raised when diagnostic inputs are malformed or statistically unusable."""


@dataclass(frozen=True)
class PlateauDiagnostic:
    best_index: int
    best_score: float
    neighbor_count: int
    neighbor_median: float
    median_relative_drop: float
    robust_neighbor_fraction: float
    plateau_score: float


@dataclass(frozen=True)
class AblationDiagnostic:
    family: str
    n_folds: int
    mean_delta: float
    median_delta: float
    positive_fold_fraction: float
    worst_fold_delta: float
    best_fold_delta: float


def parameter_plateau_diagnostic(
    results: pd.DataFrame,
    *,
    parameter_columns: Sequence[str],
    metric_column: str,
    maximize: bool = True,
    neighbor_radius: int = 1,
    tolerance_fraction: float = 0.15,
) -> PlateauDiagnostic:
    """Measure whether the best grid point sits on a broad local performance plateau.

    Neighboring configurations are defined in *grid-rank space*: each numeric
    parameter is mapped to its sorted unique values and a neighbor differs by at
    most ``neighbor_radius`` rank steps in every parameter, while differing in at
    least one parameter.

    ``plateau_score`` is the fraction of neighbors that retain performance within
    ``tolerance_fraction`` of the best score's absolute scale. A sharp isolated
    optimum therefore scores near zero; a broad stable region scores near one.
    """
    if results.empty:
        raise JudgeDiagnosticError("results must be non-empty")
    if not parameter_columns:
        raise JudgeDiagnosticError("parameter_columns must be non-empty")
    if neighbor_radius < 1:
        raise JudgeDiagnosticError("neighbor_radius must be >= 1")
    if not 0 <= tolerance_fraction <= 1:
        raise JudgeDiagnosticError("tolerance_fraction must be in [0,1]")

    required = set(parameter_columns) | {metric_column}
    missing = sorted(required - set(results.columns))
    if missing:
        raise JudgeDiagnosticError(f"missing columns: {missing}")
    if results[list(required)].isna().any().any():
        raise JudgeDiagnosticError("parameter/metric columns cannot contain NaN")

    grid_values: dict[str, list[float]] = {}
    rank_maps: dict[str, dict[float, int]] = {}
    for column in parameter_columns:
        try:
            values = sorted(float(value) for value in results[column].unique())
        except (TypeError, ValueError) as exc:
            raise JudgeDiagnosticError(f"parameter must be numeric: {column}") from exc
        grid_values[column] = values
        rank_maps[column] = {value: rank for rank, value in enumerate(values)}

    scores = results[metric_column].astype(float)
    best_label = scores.idxmax() if maximize else scores.idxmin()
    best_position = int(results.index.get_loc(best_label))
    best_row = results.loc[best_label]
    best_score = float(best_row[metric_column])
    best_ranks = {
        column: rank_maps[column][float(best_row[column])] for column in parameter_columns
    }

    neighbors: list[float] = []
    for row_label, row in results.iterrows():
        if row_label == best_label:
            continue
        rank_deltas = [
            abs(rank_maps[column][float(row[column])] - best_ranks[column])
            for column in parameter_columns
        ]
        if all(delta <= neighbor_radius for delta in rank_deltas) and any(
            delta > 0 for delta in rank_deltas
        ):
            neighbors.append(float(row[metric_column]))

    if not neighbors:
        raise JudgeDiagnosticError("best point has no grid neighbors")

    neighbor_array = np.asarray(neighbors, dtype=float)
    neighbor_median = float(np.median(neighbor_array))
    scale = max(abs(best_score), float(np.std(scores.to_numpy(dtype=float))), 1e-12)
    if maximize:
        relative_drops = (best_score - neighbor_array) / scale
        robust = neighbor_array >= best_score - tolerance_fraction * scale
    else:
        relative_drops = (neighbor_array - best_score) / scale
        robust = neighbor_array <= best_score + tolerance_fraction * scale

    median_relative_drop = float(np.median(relative_drops))
    robust_fraction = float(np.mean(robust))
    return PlateauDiagnostic(
        best_index=best_position,
        best_score=best_score,
        neighbor_count=len(neighbors),
        neighbor_median=neighbor_median,
        median_relative_drop=median_relative_drop,
        robust_neighbor_fraction=robust_fraction,
        plateau_score=robust_fraction,
    )


def feature_family_ablation(
    full_scores: Sequence[float],
    ablated_scores: Mapping[str, Sequence[float]],
    *,
    higher_is_better: bool = True,
) -> list[AblationDiagnostic]:
    """Compute paired fold-wise performance loss when each feature family is removed.

    Positive delta means the full model outperformed the ablated model when
    ``higher_is_better`` is True. For loss metrics set ``higher_is_better=False``;
    positive delta then means removing the family made the loss worse.
    """
    full = np.asarray(list(full_scores), dtype=float)
    if len(full) == 0 or np.isnan(full).any():
        raise JudgeDiagnosticError("full_scores must be non-empty and finite")

    diagnostics: list[AblationDiagnostic] = []
    for family, values in sorted(ablated_scores.items()):
        ablated = np.asarray(list(values), dtype=float)
        if len(ablated) != len(full):
            raise JudgeDiagnosticError(
                f"ablation fold count mismatch for {family}: {len(ablated)} != {len(full)}"
            )
        if np.isnan(ablated).any():
            raise JudgeDiagnosticError(f"ablation scores contain NaN: {family}")
        delta = full - ablated if higher_is_better else ablated - full
        diagnostics.append(
            AblationDiagnostic(
                family=family,
                n_folds=len(full),
                mean_delta=float(np.mean(delta)),
                median_delta=float(np.median(delta)),
                positive_fold_fraction=float(np.mean(delta > 0)),
                worst_fold_delta=float(np.min(delta)),
                best_fold_delta=float(np.max(delta)),
            )
        )
    return diagnostics
