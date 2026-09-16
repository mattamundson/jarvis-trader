from __future__ import annotations

import random
from datetime import date
from statistics import median

from pydantic import BaseModel, ConfigDict, Field


class MonteCarloObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: str = Field(min_length=1)
    trading_date: date
    return_r: float


class MonteCarloSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    n_paths: int = Field(default=10_000, gt=0)
    seed: int = 0
    loss_thresholds_r: tuple[float, ...] = (-5.0, -10.0, -20.0)


class ClusterPath(BaseModel):
    model_config = ConfigDict(frozen=True)
    sampled_clusters: tuple[tuple[date, tuple[str, ...]], ...]
    returns_r: tuple[float, ...]


class MonteCarloSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    n_paths: int
    seed: int
    cluster_count: int
    median_terminal_r: float
    median_max_drawdown_r: float
    p90_max_drawdown_r: float
    p95_max_drawdown_r: float
    p99_max_drawdown_r: float
    p95_max_losing_streak: int
    probability_negative_terminal_r: float
    probability_loss_threshold: dict[float, float]


def _group(rows: tuple[MonteCarloObservation, ...] | list[MonteCarloObservation]):
    grouped: dict[date, list[MonteCarloObservation]] = {}
    for row in rows:
        grouped.setdefault(row.trading_date, []).append(row)
    return {d: tuple(sorted(v, key=lambda r: r.observation_id)) for d, v in sorted(grouped.items())}


def draw_cluster_path(
    observations: tuple[MonteCarloObservation, ...] | list[MonteCarloObservation],
    *,
    seed: int,
) -> ClusterPath:
    grouped = _group(observations)
    if not grouped:
        raise ValueError("observations cannot be empty")
    dates = tuple(grouped)
    rng = random.Random(seed)
    sampled = [rng.choice(dates) for _ in dates]
    clusters = tuple((d, tuple(r.observation_id for r in grouped[d])) for d in sampled)
    returns = tuple(r.return_r for d in sampled for r in grouped[d])
    return ClusterPath(sampled_clusters=clusters, returns_r=returns)


def _path_stats(returns: tuple[float, ...]) -> tuple[float, float, int, float]:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    loss_streak = 0
    max_streak = 0
    min_cumulative = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
        min_cumulative = min(min_cumulative, cumulative)
        if value < 0:
            loss_streak += 1
            max_streak = max(max_streak, loss_streak)
        else:
            loss_streak = 0
    return cumulative, max_dd, max_streak, min_cumulative


def _quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    idx = int(round((len(ordered) - 1) * p))
    return ordered[idx]


def run_cluster_monte_carlo(
    observations: tuple[MonteCarloObservation, ...] | list[MonteCarloObservation],
    spec: MonteCarloSpec | None = None,
) -> MonteCarloSummary:
    cfg = spec or MonteCarloSpec()
    grouped = _group(observations)
    if not grouped:
        raise ValueError("observations cannot be empty")
    dates = tuple(grouped)
    rng = random.Random(cfg.seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    streaks: list[int] = []
    minima: list[float] = []
    for _ in range(cfg.n_paths):
        sampled = [rng.choice(dates) for _ in dates]
        returns = tuple(r.return_r for d in sampled for r in grouped[d])
        terminal, dd, streak, minimum = _path_stats(returns)
        terminals.append(terminal)
        drawdowns.append(dd)
        streaks.append(streak)
        minima.append(minimum)
    threshold_probs = {
        threshold: sum(1 for minimum in minima if minimum <= threshold) / cfg.n_paths
        for threshold in cfg.loss_thresholds_r
    }
    return MonteCarloSummary(
        n_paths=cfg.n_paths,
        seed=cfg.seed,
        cluster_count=len(dates),
        median_terminal_r=median(terminals),
        median_max_drawdown_r=median(drawdowns),
        p90_max_drawdown_r=_quantile(drawdowns, 0.90),
        p95_max_drawdown_r=_quantile(drawdowns, 0.95),
        p99_max_drawdown_r=_quantile(drawdowns, 0.99),
        p95_max_losing_streak=int(_quantile([float(x) for x in streaks], 0.95)),
        probability_negative_terminal_r=sum(1 for x in terminals if x < 0) / cfg.n_paths,
        probability_loss_threshold=threshold_probs,
    )
