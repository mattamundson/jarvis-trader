"""Phase 4 -- combinations / ensembles of relative-value survivors.

Phases 1-3 (relval) produce per-pair survivors. Phase 4 asks a different,
portfolio-level question: do two survivors that each carry an edge combine into
a book that is *risk-superior* to either alone? The answer is yes only when the
sleeves are genuinely uncorrelated -- two positive-Sharpe streams with return
correlation near zero blend into a higher-Sharpe, lower-drawdown book (the one
real free lunch in finance). Correlated sleeves add gross exposure without
diversifying, so we combine ONLY pairs with |rho| < CORR_THRESHOLD.

This does NOT manufacture edge. If both sleeves are forward-shadow-unconfirmed,
the ensemble is forward-shadow-unconfirmed too -- combination is a portfolio-
construction recommendation, not a validation upgrade. Every metric here is
in-sample on the sleeves' shared window and is labelled as such.

The PnL streams come from the SAME `_run_spread` engine the gauntlet used, at
each survivor's default params -- no re-tuning at the portfolio layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.factory.data import load_bars
from backtest.factory.relval import ANNUALIZATION, CAPITAL, _run_spread, build_spread

# Sleeves with return correlation at/above this are NOT combined: they add gross
# exposure without diversifying. 0.3 is the standard "uncorrelated enough" bar.
CORR_THRESHOLD = 0.30


@dataclass
class Survivor:
    """A relval pair that PASSED robustness -- a forward-shadow candidate sleeve."""

    name: str
    leg_a: str
    leg_b: str
    params: dict = field(
        default_factory=lambda: {
            "window": 60,
            "entry_z": 2.0,
            "exit_z": 0.5,
            "stop_z": 4.0,
            "cost_bps_per_leg": 1.0,
        }
    )


def sleeve_bar_pnl(surv: Survivor, timeframe: str, cache_dir: str) -> pd.Series:
    """Per-bar PnL (return units on a $1/leg dollar-neutral book) indexed by
    timestamp -- the same `bar_pnl` the gauntlet scored, just keyed by time so
    sleeves can be aligned and blended."""
    a = load_bars(surv.leg_a, timeframe, cache_dir)["close"]
    b = load_bars(surv.leg_b, timeframe, cache_dir)["close"]
    sp = build_spread(a, b, surv.params["window"])
    bar_pnl, _ = _run_spread(a, b, **surv.params)
    return pd.Series(bar_pnl, index=sp.index, name=surv.name)


def _ann(timeframe: str) -> float:
    return float(ANNUALIZATION.get(timeframe, np.sqrt(252 * 6.5)))


def sharpe(r: pd.Series, timeframe: str = "1h") -> float:
    """Annualized Sharpe over IN-POSITION bars (flat bars carry no signal)."""
    act = r[r != 0.0]
    if act.size <= 1 or act.std() == 0:
        return 0.0
    return float(act.mean() / act.std() * _ann(timeframe))


def max_dd_frac(r: pd.Series) -> float:
    """Capital-relative max drawdown FRACTION (matches backtest_spread's contract)."""
    eq = CAPITAL + np.cumsum(r.to_numpy() * CAPITAL)
    peak = np.maximum.accumulate(eq)
    return float(((peak - eq) / np.where(peak > 0, peak, 1.0)).max())


def ann_return(r: pd.Series, timeframe: str = "1h") -> float:
    """Annualized mean return on the dollar-neutral book (bars/yr = ann^2)."""
    return float(r.mean() * (_ann(timeframe) ** 2))


def align_sleeves(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Restrict to the shared date range, union timestamps, fill idle bars with 0
    (a sleeve contributes nothing on a bar it has no position / no data)."""
    lo, hi = max(a.index[0], b.index[0]), min(a.index[-1], b.index[-1])
    idx = a.index.union(b.index)
    idx = idx[(idx >= lo) & (idx <= hi)]
    return a.reindex(idx).fillna(0.0), b.reindex(idx).fillna(0.0)


def pair_correlation(a: pd.Series, b: pd.Series) -> float:
    """Return correlation over bars where at least one sleeve is live (both-flat
    bars are uninformative and would bias the estimate toward 0)."""
    live = (a != 0.0) | (b != 0.0)
    if int(live.sum()) <= 2:
        return float("nan")
    return float(np.corrcoef(a[live], b[live])[0, 1])


def inverse_vol_weights(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Equal-RISK weights from in-position vol, normalized to sum 1."""
    va, vb = a[a != 0].std(), b[b != 0].std()
    if not (va > 0 and vb > 0):
        return 0.5, 0.5
    wa, wb = 1.0 / va, 1.0 / vb
    tot = wa + wb
    return wa / tot, wb / tot


@dataclass
class ComboResult:
    name_a: str
    name_b: str
    correlation: float
    combined: bool  # did |rho| clear the threshold?
    n_bars: int
    window_start: str
    window_end: str
    sharpe_a: float
    sharpe_b: float
    dd_a: float
    dd_b: float
    sharpe_equal: float
    dd_equal: float
    ret_equal: float
    sharpe_invvol: float
    dd_invvol: float
    w_invvol: tuple[float, float]
    improves: bool  # ensemble Sharpe > best standalone AND dd <= best standalone


def combine(a_surv: Survivor, b_surv: Survivor, timeframe: str, cache_dir: str) -> ComboResult:
    """Measure the diversification benefit of blending two survivors. No tuning;
    default params; in-sample on the shared window (labelled as such upstream)."""
    a = sleeve_bar_pnl(a_surv, timeframe, cache_dir)
    b = sleeve_bar_pnl(b_surv, timeframe, cache_dir)
    a, b = align_sleeves(a, b)
    rho = pair_correlation(a, b)
    combined = abs(rho) < CORR_THRESHOLD if not np.isnan(rho) else False

    sa, sb = sharpe(a, timeframe), sharpe(b, timeframe)
    da, db = max_dd_frac(a), max_dd_frac(b)
    equal = 0.5 * a + 0.5 * b
    wa, wb = inverse_vol_weights(a, b)
    invvol = wa * a + wb * b

    s_eq, s_iv = sharpe(equal, timeframe), sharpe(invvol, timeframe)
    d_eq, d_iv = max_dd_frac(equal), max_dd_frac(invvol)
    best_s, best_dd = max(sa, sb), min(da, db)
    improves = combined and s_eq > best_s and d_eq <= best_dd

    return ComboResult(
        name_a=a_surv.name,
        name_b=b_surv.name,
        correlation=rho,
        combined=combined,
        n_bars=len(a),
        window_start=str(a.index[0].date()),
        window_end=str(a.index[-1].date()),
        sharpe_a=sa,
        sharpe_b=sb,
        dd_a=da,
        dd_b=db,
        sharpe_equal=s_eq,
        dd_equal=d_eq,
        ret_equal=ann_return(equal, timeframe),
        sharpe_invvol=s_iv,
        dd_invvol=d_iv,
        w_invvol=(wa, wb),
        improves=improves,
    )


def run_combos(survivors: list[Survivor], timeframe: str, cache_dir: str) -> list[ComboResult]:
    """All unordered survivor pairs through the combination test."""
    out: list[ComboResult] = []
    for i in range(len(survivors)):
        for j in range(i + 1, len(survivors)):
            out.append(combine(survivors[i], survivors[j], timeframe, cache_dir))
    return out


def render_combos_report(results: list[ComboResult], timeframe: str) -> str:
    lines = [
        "# Strategy-Factory Report -- Combinations (Phase 4)",
        "",
        f"- Survivor pairs tested: **{len(results)}**  |  TF: {timeframe}",
        f"- Correlation threshold for blending: |rho| < {CORR_THRESHOLD}",
        "- IN-SAMPLE on each pair's shared window. A diversification benefit here is a",
        "  portfolio-construction recommendation, NOT a validation upgrade -- the",
        "  forward shadow remains the only honest deploy gate.",
        "",
        "| Pair A | Pair B | corr | window | Sharpe A/B | best->equal-wt | maxDD A/B->ens | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        verdict = "DIVERSIFIES" if r.improves else ("blend" if r.combined else "too correlated")
        lines.append(
            f"| {r.name_a} | {r.name_b} | {r.correlation:+.3f} "
            f"| {r.window_start}->{r.window_end} ({r.n_bars}b) "
            f"| {r.sharpe_a:.2f}/{r.sharpe_b:.2f} "
            f"| {max(r.sharpe_a, r.sharpe_b):.2f}->{r.sharpe_equal:.2f} "
            f"| {100 * r.dd_a:.2f}%/{100 * r.dd_b:.2f}%->{100 * r.dd_equal:.2f}% "
            f"| {verdict} |"
        )
    return "\n".join(lines) + "\n"
