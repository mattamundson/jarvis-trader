from __future__ import annotations

import itertools
import json
import math
import platform
from collections import defaultdict
from enum import StrEnum
from hashlib import sha256
from statistics import fmean

import numpy as np
import scipy
import statsmodels
from pydantic import BaseModel, ConfigDict, Field
from scipy import stats

from morning_alpha.research.bootstrap import BootstrapClusterUnit, bootstrap_edge_ci
from morning_alpha.research.cost_break_even import analyze_cost_break_even
from morning_alpha.research.permutation import (
    date_cluster_edge_permutation,
    paired_edge_permutation,
)
from morning_alpha.research.statistical_models import MatchedEdgeObservation


class ConformanceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class ConformanceCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    internal_value: float
    reference_value: float
    absolute_difference: float = Field(ge=0)
    relative_difference: float = Field(ge=0)
    tolerance: float = Field(ge=0)
    status: ConformanceStatus
    method: str = Field(min_length=1)


class ConformanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    observed_mean_edge: float
    seed: int
    resamples: int = Field(gt=0)
    fixture_hash: str = Field(min_length=64, max_length=64)
    python_version: str
    numpy_version: str
    scipy_version: str
    statsmodels_version: str
    cases: tuple[ConformanceCaseResult, ...]
    overall_status: ConformanceStatus
    report_id: str = Field(min_length=64, max_length=64)

    def case(self, name: str) -> ConformanceCaseResult:
        for item in self.cases:
            if item.name == name:
                return item
        raise KeyError(name)


def _hash_payload(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def _fixture_hash(rows: tuple[MatchedEdgeObservation, ...]) -> str:
    return _hash_payload([row.model_dump(mode="json") for row in rows])


def _case(name: str, internal: float, reference: float, tolerance: float, method: str) -> ConformanceCaseResult:
    absolute = abs(float(internal) - float(reference))
    denom = max(abs(float(reference)), 1e-15)
    relative = absolute / denom
    status = ConformanceStatus.VERIFIED if absolute <= tolerance else ConformanceStatus.FAILED
    return ConformanceCaseResult(
        name=name,
        internal_value=float(internal),
        reference_value=float(reference),
        absolute_difference=absolute,
        relative_difference=relative,
        tolerance=tolerance,
        status=status,
        method=method,
    )


def _scipy_paired_sign_flip_p(edges: np.ndarray) -> float:
    result = stats.permutation_test(
        (edges,),
        lambda x, axis=-1: np.mean(x, axis=axis),
        permutation_type="samples",
        vectorized=True,
        n_resamples=np.inf,
        alternative="greater",
    )
    return float(result.pvalue)


def _exhaustive_cluster_p(rows: tuple[MatchedEdgeObservation, ...]) -> float:
    groups: dict[object, list[float]] = defaultdict(list)
    for row in rows:
        groups[row.trading_date].append(row.edge)
    keys = sorted(groups, key=str)
    if len(keys) < 2:
        raise ValueError("cluster conformance requires at least two date clusters")
    observed = fmean(row.edge for row in rows)
    null: list[float] = []
    for signs in itertools.product((-1, 1), repeat=len(keys)):
        sample: list[float] = []
        for key, sign in zip(keys, signs):
            sample.extend(value * sign for value in groups[key])
        null.append(fmean(sample))
    return sum(value >= observed for value in null) / len(null)


def _scipy_percentile_ci(edges: np.ndarray, *, seed: int, resamples: int, confidence: float = 0.95) -> tuple[float, float]:
    result = stats.bootstrap(
        (edges,),
        np.mean,
        vectorized=False,
        n_resamples=resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(seed),
    )
    return float(result.confidence_interval.low), float(result.confidence_interval.high)


def run_statistical_conformance(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 20260915,
    resamples: int = 10_000,
    permutation_tolerance: float = 1e-12,
    bootstrap_tolerance: float = 0.03,
) -> ConformanceReport:
    rows = tuple(observations)
    if len(rows) < 2:
        raise ValueError("statistical conformance requires at least two observations")
    if resamples <= 0:
        raise ValueError("resamples must be positive")
    edges = np.asarray([row.edge for row in rows], dtype=float)

    paired = paired_edge_permutation(rows, seed=seed, permutations=resamples, exact_max_n=20)
    scipy_p = _scipy_paired_sign_flip_p(edges)
    cases: list[ConformanceCaseResult] = [
        _case(
            "paired_permutation_exact_vs_scipy",
            paired.one_sided_p,
            scipy_p,
            permutation_tolerance,
            "internal exact sign-flip vs scipy.stats.permutation_test(samples)",
        )
    ]

    date_count = len({row.trading_date for row in rows})
    if date_count >= 2 and date_count <= 20:
        cluster = date_cluster_edge_permutation(rows, seed=seed, permutations=resamples, exact_max_clusters=20)
        cluster_reference = _exhaustive_cluster_p(rows)
        cases.append(
            _case(
                "date_cluster_permutation_vs_exhaustive",
                cluster.one_sided_p,
                cluster_reference,
                permutation_tolerance,
                "internal date-cluster sign-flip vs independent exhaustive cluster enumeration",
            )
        )

    internal_bootstrap = bootstrap_edge_ci(
        rows,
        cluster_unit=BootstrapClusterUnit.IID,
        seed=seed,
        resamples=resamples,
        confidence=0.95,
        min_clusters=2,
    )
    scipy_lower, scipy_upper = _scipy_percentile_ci(edges, seed=seed, resamples=resamples)
    cases.extend(
        [
            _case(
                "iid_bootstrap_lower_vs_scipy",
                internal_bootstrap.lower,
                scipy_lower,
                bootstrap_tolerance,
                "internal IID percentile bootstrap vs scipy.stats.bootstrap percentile",
            ),
            _case(
                "iid_bootstrap_upper_vs_scipy",
                internal_bootstrap.upper,
                scipy_upper,
                bootstrap_tolerance,
                "internal IID percentile bootstrap vs scipy.stats.bootstrap percentile",
            ),
        ]
    )

    cost = analyze_cost_break_even(rows, realistic_bps=5.0)
    if cost.available and cost.break_even_bps is not None:
        gross = fmean(float(row.gross_r) for row in rows)
        coefficient = fmean(float(row.cost_r_per_bps) for row in rows)
        direct = max(0.0, gross / coefficient)
        cases.append(
            _case(
                "cost_break_even_closed_form",
                cost.break_even_bps,
                direct,
                1e-12,
                "internal break-even vs independent closed-form mean(gross_r)/mean(cost_r_per_bps)",
            )
        )

    overall = (
        ConformanceStatus.VERIFIED
        if all(case.status is ConformanceStatus.VERIFIED for case in cases)
        else ConformanceStatus.FAILED
    )
    fixture_hash = _fixture_hash(rows)
    identity = {
        "observed_mean_edge": fmean(row.edge for row in rows),
        "seed": seed,
        "resamples": resamples,
        "fixture_hash": fixture_hash,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
        },
        "cases": [case.model_dump(mode="json") for case in cases],
        "overall_status": overall.value,
    }
    return ConformanceReport(
        observed_mean_edge=fmean(row.edge for row in rows),
        seed=seed,
        resamples=resamples,
        fixture_hash=fixture_hash,
        python_version=platform.python_version(),
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
        statsmodels_version=statsmodels.__version__,
        cases=tuple(cases),
        overall_status=overall,
        report_id=_hash_payload(identity),
    )
