from __future__ import annotations

import itertools
import math
import random
from statistics import fmean, stdev

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VariantReturnSeries(BaseModel):
    model_config = ConfigDict(frozen=True)
    variant_id: str = Field(min_length=1)
    returns: tuple[float, ...]

    @model_validator(mode="after")
    def validate_series(self) -> "VariantReturnSeries":
        if len(self.returns) < 4:
            raise ValueError("variant series requires at least 4 observations")
        if not all(math.isfinite(x) for x in self.returns):
            raise ValueError("variant returns must be finite")
        return self


class PBOResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    pbo: float
    split_count: int
    oos_logits: tuple[float, ...]
    selected_variants: tuple[str, ...]
    method: str = "cscv_pbo_mean_sharpe_rank"


class BootstrapMultipleTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    best_variant_id: str
    observed_statistic: float
    p_value: float
    n_bootstrap: int
    block_length: int
    method: str
    active_variant_count: int


class StepdownResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_p_values: dict[str, float]
    adjusted_p_values: dict[str, float]
    method: str = "romano_wolf_style_maxT_block_bootstrap"
    n_bootstrap: int
    block_length: int


def _validate_aligned(series):
    rows = tuple(series)
    if len(rows) < 2:
        raise ValueError("at least two variants are required")
    n = len(rows[0].returns)
    if any(len(row.returns) != n for row in rows):
        raise ValueError("variant return series must be aligned")
    if len({row.variant_id for row in rows}) != len(rows):
        raise ValueError("variant IDs must be unique")
    return rows, n


def _score(values) -> float:
    if not values:
        return float("-inf")
    avg = fmean(values)
    if len(values) < 2:
        return avg
    sd = stdev(values)
    return avg / sd if sd > 0 else (float("inf") if avg > 0 else avg)


def cscv_pbo(series, *, partitions: int = 8) -> PBOResult:
    rows, n = _validate_aligned(series)
    if partitions < 4 or partitions % 2:
        raise ValueError("partitions must be an even integer >= 4")
    if n < partitions or n % partitions:
        raise ValueError("observation count must be divisible by partitions")
    block = n // partitions
    blocks = tuple(tuple(range(i * block, (i + 1) * block)) for i in range(partitions))
    logits, selected = [], []
    for chosen in itertools.combinations(range(partitions), partitions // 2):
        chosen_set = set(chosen)
        is_idx = tuple(i for b in chosen for i in blocks[b])
        oos_idx = tuple(i for b in range(partitions) if b not in chosen_set for i in blocks[b])
        is_scores = {row.variant_id: _score(tuple(row.returns[i] for i in is_idx)) for row in rows}
        winner = max(is_scores, key=is_scores.get)
        selected.append(winner)
        oos_perf = {row.variant_id: fmean(row.returns[i] for i in oos_idx) for row in rows}
        ordered = sorted(oos_perf, key=lambda k: oos_perf[k])
        rank = ordered.index(winner) + 1
        omega = rank / (len(rows) + 1)
        logits.append(math.log(omega / (1.0 - omega)))
    return PBOResult(pbo=sum(v <= 0 for v in logits)/len(logits), split_count=len(logits), oos_logits=tuple(logits), selected_variants=tuple(selected))


def _circular_block_indices(n: int, block_length: int, rng: random.Random) -> tuple[int, ...]:
    if block_length < 1:
        raise ValueError("block_length must be >= 1")
    out = []
    while len(out) < n:
        start = rng.randrange(n)
        out.extend((start + j) % n for j in range(block_length))
    return tuple(out[:n])


def _means(rows):
    return {row.variant_id: fmean(row.returns) for row in rows}


def reality_check(series, *, n_bootstrap: int = 2000, block_length: int = 5, seed: int = 0) -> BootstrapMultipleTestResult:
    rows, n = _validate_aligned(series)
    means = _means(rows)
    winner = max(means, key=means.get)
    observed = math.sqrt(n) * max(means.values())
    centered = {row.variant_id: tuple(x-means[row.variant_id] for x in row.returns) for row in rows}
    rng = random.Random(seed); exceed = 0
    for _ in range(n_bootstrap):
        idx = _circular_block_indices(n, block_length, rng)
        stat = max(math.sqrt(n)*fmean(centered[row.variant_id][i] for i in idx) for row in rows)
        exceed += stat >= observed
    p = (exceed+1)/(n_bootstrap+1)
    return BootstrapMultipleTestResult(best_variant_id=winner, observed_statistic=observed, p_value=p, n_bootstrap=n_bootstrap, block_length=block_length, method="white_reality_check_style_block_bootstrap", active_variant_count=len(rows))


def _t_stat(values: tuple[float, ...]) -> float:
    avg=fmean(values); sd=stdev(values) if len(values)>1 else 0.0
    if sd==0:
        return float("inf") if avg>0 else (float("-inf") if avg<0 else 0.0)
    return math.sqrt(len(values))*avg/sd


def spa_style_test(series, *, n_bootstrap: int = 2000, block_length: int = 5, seed: int = 0) -> BootstrapMultipleTestResult:
    rows,n=_validate_aligned(series)
    cutoff=-math.sqrt(2.0*math.log(max(math.log(max(n,3)),1.0000001)))
    tstats={row.variant_id:_t_stat(row.returns) for row in rows}
    active=tuple(row for row in rows if tstats[row.variant_id]>=cutoff) or (max(rows,key=lambda r:tstats[r.variant_id]),)
    winner=max(active,key=lambda r:tstats[r.variant_id]); observed=max(tstats[row.variant_id] for row in active)
    means=_means(active); sds={r.variant_id:stdev(r.returns) if len(r.returns)>1 else 0.0 for r in active}; centered={r.variant_id:tuple(x-means[r.variant_id] for x in r.returns) for r in active}
    rng=random.Random(seed); exceed=0
    for _ in range(n_bootstrap):
        idx=_circular_block_indices(n,block_length,rng); stats=[]
        for row in active:
            sd=sds[row.variant_id]; stats.append(0.0 if sd<=0 else math.sqrt(n)*fmean(centered[row.variant_id][i] for i in idx)/sd)
        exceed += max(stats)>=observed
    return BootstrapMultipleTestResult(best_variant_id=winner.variant_id, observed_statistic=observed, p_value=(exceed+1)/(n_bootstrap+1), n_bootstrap=n_bootstrap, block_length=block_length, method="hansen_spa_style_consistent_truncation_block_bootstrap", active_variant_count=len(active))


def romano_wolf_stepdown(series, *, n_bootstrap: int = 2000, block_length: int = 5, seed: int = 0) -> StepdownResult:
    rows,n=_validate_aligned(series); observed={r.variant_id:_t_stat(r.returns) for r in rows}; means=_means(rows); sds={r.variant_id:stdev(r.returns) if len(r.returns)>1 else 0.0 for r in rows}; centered={r.variant_id:tuple(x-means[r.variant_id] for x in r.returns) for r in rows}
    rng=random.Random(seed); boot=[]
    for _ in range(n_bootstrap):
        idx=_circular_block_indices(n,block_length,rng); sample={}
        for r in rows:
            sd=sds[r.variant_id]; sample[r.variant_id]=0.0 if sd<=0 else math.sqrt(n)*fmean(centered[r.variant_id][i] for i in idx)/sd
        boot.append(sample)
    raw={vid:(1+sum(s[vid]>=observed[vid] for s in boot))/(n_bootstrap+1) for vid in observed}; ordered=sorted(observed,key=observed.get,reverse=True); adjusted={}; running=0.0
    for pos,vid in enumerate(ordered):
        remaining=ordered[pos:]; p=(1+sum(max(s[k] for k in remaining)>=observed[vid] for s in boot))/(n_bootstrap+1); running=max(running,p,raw[vid]); adjusted[vid]=min(1.0,running)
    return StepdownResult(raw_p_values=raw, adjusted_p_values=adjusted, n_bootstrap=n_bootstrap, block_length=block_length)
