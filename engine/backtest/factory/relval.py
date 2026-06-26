"""Relative-value (pairs) module for the strategy factory.

The intraday-directional factory is exhausted (660 parameterizations, 0 survivors).
Relative-value is a STRUCTURALLY different class: mean reversion on a *spread*
between two correlated instruments, not directional momentum on a price. It reuses
the whole rigor stack -- WFO windows, gate-v2, PBO, globally-deflated Sharpe -- but
needs its own spread constructor and a dollar-neutral two-leg backtester.

Spread (no look-ahead, no fitted beta):
    spread_t = log(close_A_t) - log(close_B_t)        # 1:1 log spread, dollar-neutral
    z_t      = (spread_t - mean(spread)_{t-1}) / std(spread)_{t-1}   # rolling, shifted

Signal (mean reversion):
    z <= -entry_z  -> LONG the spread  (buy A, sell B)
    z >= +entry_z  -> SHORT the spread (sell A, buy B)
    |z| <= exit_z  -> flatten
    |z| >= stop_z  -> stop out (spread blew out -- pair may have de-correlated)

PnL per bar in-position = position * d(spread) = position * (ret_A - ret_B), the
dollar-neutral pairs return. Each round trip pays cost on BOTH legs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from backtest._constants import (
    COST_TIER_ORDER,
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
)
from backtest._gate_v2_trade_metrics import trade_level_dsr, trade_level_mc_95th_dd
from backtest.factory.data import has_cache, load_bars
from backtest.factory.funnel import (
    SMOKE_LOW_SAMPLE_TRADES,
    SMOKE_MIN_PF,
    SMOKE_MIN_SHARPE,
    SMOKE_MIN_TRADES,
    BacktestMetrics,
    _windows,
)
from backtest.factory.pbo import probability_of_backtest_overfitting
from backtest.factory.results_db import ResultsDB

ANNUALIZATION = {"1h": np.sqrt(252 * 6.5), "30m": np.sqrt(252 * 13), "1d": np.sqrt(252)}
# Realistic round-trip cost per leg (bps). A micro-future round turn ~= 0.5-1 bp.
REALISTIC_COST_BPS = 1.0
# Notional capital deployed per leg. A pairs book runs ~1x capital per leg
# (~2x gross); the gate's drawdown/DSR are computed capital-relative on this base,
# so it must match the single-instrument factory's $50K so verdicts are comparable.
CAPITAL = 50_000.0


def build_spread(close_a: pd.Series, close_b: pd.Series, window: int) -> pd.DataFrame:
    """Align two close series and return a frame with spread + rolling z-score.

    Mean/std are shifted one bar so the z at time t uses only information available
    BEFORE t (no look-ahead).
    """
    df = pd.DataFrame({"a": close_a, "b": close_b}).dropna()
    spread = np.log(df["a"]) - np.log(df["b"])
    mean = spread.rolling(window).mean().shift(1)
    std = spread.rolling(window).std().shift(1)
    z = (spread - mean) / std.replace(0, np.nan)
    return pd.DataFrame({"spread": spread, "z": z}, index=df.index)


def _run_spread(
    close_a: pd.Series,
    close_b: pd.Series,
    *,
    window: int,
    entry_z: float,
    exit_z: float,
    stop_z: float,
    cost_bps_per_leg: float,
) -> tuple[np.ndarray, list[float]]:
    """Core z-score reversion engine. Returns (bar_pnl, trade_pnls) in
    spread-RETURN units (dollar-neutral $1-per-leg book). Both the metrics
    wrapper and the per-trade dollar extractor build on this one engine."""
    sp = build_spread(close_a, close_b, window)
    spread, z = sp["spread"].to_numpy(), sp["z"].to_numpy()
    n = len(sp)
    if n < window + 5:
        return np.zeros(0), []

    d_spread = np.diff(spread, prepend=spread[0])  # bar-over-bar spread change
    pos = 0  # current position: +1 long spread, -1 short spread, 0 flat
    cost = cost_bps_per_leg * 2.0 / 1e4  # round-trip cost (both legs) in spread-return units
    bar_pnl = np.zeros(n)
    trade_pnls: list[float] = []
    cur_trade = 0.0

    for i in range(1, n):
        zi = z[i]
        if np.isnan(zi):
            continue
        # accrue PnL on the position held into bar i
        if pos != 0:
            bar_pnl[i] = pos * d_spread[i]
            cur_trade += bar_pnl[i]
        # state transitions (decided on this bar's z, applied to next bar's accrual)
        if pos == 0:
            if zi <= -entry_z:
                pos = 1
            elif zi >= entry_z:
                pos = -1
        else:
            blew_out = abs(zi) >= stop_z
            reverted = abs(zi) <= exit_z
            if reverted or blew_out:
                cur_trade -= cost  # pay round-trip cost on close
                trade_pnls.append(cur_trade)
                cur_trade = 0.0
                pos = 0
    # close any open trade at the end
    if pos != 0:
        cur_trade -= cost
        trade_pnls.append(cur_trade)
    return bar_pnl, trade_pnls


def spread_trade_dollars(
    close_a: pd.Series,
    close_b: pd.Series,
    *,
    window: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    cost_bps_per_leg: float = REALISTIC_COST_BPS,
    capital: float = CAPITAL,
) -> list[float]:
    """Per-trade PnL in DOLLARS (return units x notional capital per leg).

    These are the inputs the trade-level gate metrics (`trade_level_mc_95th_dd`,
    `trade_level_dsr`) need -- a USD PnL per closed trade, capital-relative.
    """
    _, trade_pnls = _run_spread(
        close_a,
        close_b,
        window=window,
        entry_z=entry_z,
        exit_z=exit_z,
        stop_z=stop_z,
        cost_bps_per_leg=cost_bps_per_leg,
    )
    return [p * capital for p in trade_pnls]


def backtest_spread(
    close_a: pd.Series,
    close_b: pd.Series,
    *,
    window: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    cost_bps_per_leg: float = 1.0,
    timeframe: str = "1h",
    capital: float = CAPITAL,
) -> BacktestMetrics:
    """Vectorized dollar-neutral z-score reversion backtest. Returns BacktestMetrics
    so the gauntlet can treat it identically to a single-instrument result.

    `max_drawdown_pct` is a capital-relative FRACTION (0.05 == 5%), matching the
    OOSResult contract gate-v2 expects (a 100x units error here silently inflates
    the MC drawdown by 100 and fails every pair).
    """
    bar_pnl, trade_pnls = _run_spread(
        close_a,
        close_b,
        window=window,
        entry_z=entry_z,
        exit_z=exit_z,
        stop_z=stop_z,
        cost_bps_per_leg=cost_bps_per_leg,
    )
    n_trades = len(trade_pnls)
    if n_trades == 0:
        return BacktestMetrics(
            profit_factor=0.0, sharpe_ratio=0.0, max_drawdown_pct=0.0, total_trades=0
        )

    tp = np.array(trade_pnls)
    gains = tp[tp > 0].sum()
    losses = -tp[tp < 0].sum()
    pf = float(gains / losses) if losses > 0 else (5.0 if gains > 0 else 0.0)

    ann = ANNUALIZATION.get(timeframe, np.sqrt(252 * 6.5))
    active = bar_pnl[bar_pnl != 0.0]
    sharpe = (
        float(active.mean() / active.std() * ann) if active.size > 1 and active.std() > 0 else 0.0
    )

    # Capital-relative equity curve: start at `capital`, add per-bar dollar PnL
    # (bar_pnl is a fractional return on the dollar-neutral book). Drawdown as a
    # fraction of the running peak -- the same scale the single-instrument path uses.
    equity = capital + np.cumsum(bar_pnl * capital)
    peak = np.maximum.accumulate(equity)
    dd_frac = (peak - equity) / np.where(peak > 0, peak, 1.0)
    max_dd_frac = float(dd_frac.max())

    return BacktestMetrics(
        profit_factor=pf,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd_frac,
        total_trades=int(n_trades),
    )


# --------------------------------------------------------------------------- #
# Pairs + the gauntlet (reuses the single-instrument WFO/gate/PBO/DSR machinery)
# --------------------------------------------------------------------------- #


@dataclass
class Pair:
    name: str
    leg_a: str
    leg_b: str
    economic_rationale: str
    timeframes: list[str]
    default_params: dict
    param_grid: dict = field(default_factory=dict)

    def n_param_combos(self) -> int:
        if not self.param_grid:
            return 1
        out = 1
        for v in self.param_grid.values():
            out *= len(v)
        return out


def relval_pairs() -> list[Pair]:
    """Cointegrated cross pairs -- the liquid ones with bar data.

    Same-underlying pairs (e.g. MES/ES, MGC/GC) are EXCLUDED: they are the same
    instrument at different multipliers, perfectly cointegrated by construction
    with no tradeable edge. Each pair is a genuine cross-instrument relative-value
    bet. Four equity-index crosses plus one rates-curve pair (ZB/ZN), each
    pre-registered with an economic rationale before any result is seen.
    """
    common = {
        "default_params": {"window": 60, "entry_z": 2.0, "exit_z": 0.5, "stop_z": 4.0},
        "param_grid": {"window": [40, 60, 120], "entry_z": [1.5, 2.0, 2.5], "exit_z": [0.25, 0.5]},
        "timeframes": ["1h"],
    }
    return [
        Pair(
            name="MES_MNQ",
            leg_a="MES",
            leg_b="MNQ",
            economic_rationale="S&P 500 vs Nasdaq-100: both driven by the common US large-cap "
            "factor, so their spread isolates the tech/broad rotation, which mean-reverts intraday "
            "as sector flows rebalance.",
            **common,
        ),
        Pair(
            name="MES_M2K",
            leg_a="MES",
            leg_b="M2K",
            economic_rationale="Large-cap (S&P) vs small-cap (Russell 2000): the spread is a "
            "risk-on/off size factor that mean-reverts as breadth oscillates around the prevailing "
            "regime.",
            **common,
        ),
        Pair(
            name="MNQ_M2K",
            leg_a="MNQ",
            leg_b="M2K",
            economic_rationale="Nasdaq tech vs small-cap Russell: the widest size/style spread in "
            "the index complex; growth-vs-small rotation tends to overshoot and snap back intraday.",
            **common,
        ),
        Pair(
            name="ES_NQ",
            leg_a="ES",
            leg_b="NQ",
            economic_rationale="Full-size S&P vs Nasdaq -- the deepest, most-arbitraged index "
            "cross; the spread mean-reverts around the common market factor on a sector-rotation "
            "horizon.",
            **common,
        ),
        Pair(
            name="ZB_ZN",
            leg_a="ZB",
            leg_b="ZN",
            economic_rationale="30y T-bond vs 10y T-note: both driven by the common rates factor, "
            "so their spread is the long-end curve slope, which mean-reverts as duration positioning "
            "rebalances around the prevailing curve regime. NOTE: this is a 1:1 LOG spread, not "
            "DV01-weighted -- a deliberate first-pass simplification (ZB has more duration than ZN); "
            "a real edge here would justify a duration-neutral refinement. Data starts 2025-06, so "
            "the WFO window count is thin and the result is regime-limited.",
            **common,
        ),
    ]


def _aligned(bars_a: pd.DataFrame, bars_b: pd.DataFrame) -> pd.DataFrame:
    """Inner-join two bar frames on timestamp -> columns a, b (close prices)."""
    df = pd.DataFrame({"a": bars_a["close"], "b": bars_b["close"]}).dropna()
    return df


def _grid(pair: Pair) -> list[dict]:
    if not pair.param_grid:
        return [dict(pair.default_params)]
    keys = list(pair.param_grid)
    return [
        {**pair.default_params, **dict(zip(keys, combo, strict=True))}
        for combo in product(*(pair.param_grid[k] for k in keys))
    ]


def smoke_test_pair(
    pair: Pair, bars_a: pd.DataFrame, bars_b: pd.DataFrame, timeframe: str
) -> tuple[bool, dict]:
    """Pre-cost reversion edge, then realistic-cost survival -- mirrors funnel.smoke_test."""
    al = _aligned(bars_a, bars_b)
    pre = backtest_spread(
        al["a"], al["b"], timeframe=timeframe, cost_bps_per_leg=0.0, **pair.default_params
    )
    low_sample = pre.total_trades < SMOKE_LOW_SAMPLE_TRADES
    base = {
        "stage": "smoke",
        "pre_sharpe": pre.sharpe_ratio,
        "pre_pf": pre.profit_factor,
        "trades": pre.total_trades,
        "low_sample": low_sample,
    }
    if pre.total_trades < SMOKE_MIN_TRADES:
        return False, {
            **base,
            "kill_reason": f"insufficient trades to evaluate (<{SMOKE_MIN_TRADES})",
        }
    if pre.sharpe_ratio < SMOKE_MIN_SHARPE or pre.profit_factor < SMOKE_MIN_PF:
        return False, {**base, "kill_reason": "pre-cost sharpe/pf below floor"}
    post = backtest_spread(
        al["a"],
        al["b"],
        timeframe=timeframe,
        cost_bps_per_leg=REALISTIC_COST_BPS,
        **pair.default_params,
    )
    survives = post.profit_factor > SMOKE_MIN_PF
    return survives, {
        **base,
        "post_cost_pf": post.profit_factor,
        "post_cost_sharpe": post.sharpe_ratio,
        "kill_reason": None if survives else "does not survive realistic cost",
    }


@dataclass
class _Trade:
    """Duck-typed trade with a USD `.pnl` -- the only field the trade-level gate
    metrics (`concat_oos_trade_pnls`) read."""

    pnl: float


@dataclass
class _OOSWin:
    """Duck-typed OOS window carrying its per-trade USD PnLs, so the centralized
    `trade_level_mc_95th_dd` / `trade_level_dsr` (and PF/consistency helpers) treat
    a pair exactly like a single-instrument WFO window."""

    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    trades: list[_Trade]


def relval_gauntlet(
    pair: Pair,
    bars_a: pd.DataFrame,
    bars_b: pd.DataFrame,
    timeframe: str,
    global_trial_count: int,
) -> dict:
    """Walk-forward + dual-path gate-v2 + PBO for one pair, using the centralized
    TRADE-LEVEL risk metrics.

    The shared `wfo_lifecycle.compute_gate_v2` derives mc_95th_dd and DSR from
    window aggregates (95th-pct of per-window DDs; DSR from the mean of per-window
    annualized Sharpes). Both are mis-specified for sparse strategies -- the DSR in
    particular rounds to a fake 1.0 (see `_gate_v2_trade_metrics` docstring). So we
    replicate the dual-path verdict here with `trade_level_mc_95th_dd` /
    `trade_level_dsr` over the pooled OOS trade list, deflating the Sharpe by the
    GLOBAL trial count to keep the factory's multiple-testing honest.
    """
    al = _aligned(bars_a, bars_b)
    windows = _windows(al)
    grid = _grid(pair)
    n_combos = len(grid)
    if not windows:
        return {"verdict": "FAIL", "reason": "insufficient data for WFO windows"}

    def _bt(seg: pd.DataFrame, params: dict, cost: float) -> BacktestMetrics:
        return backtest_spread(
            seg["a"], seg["b"], timeframe=timeframe, cost_bps_per_leg=cost, **params
        )

    oos_wins: list[_OOSWin] = []
    for win in windows:
        tr = al[(al.index >= win["tr_s"]) & (al.index < win["tr_e"])]
        te = al[(al.index >= win["te_s"]) & (al.index <= win["te_e"])]
        best_pf, best_params = -1.0, None
        for params in grid:
            m = _bt(tr, params, 0.0)
            pf = min(m.profit_factor, 5.0) if np.isfinite(m.profit_factor) else 5.0
            if m.total_trades >= 5 and pf > best_pf:
                best_pf, best_params = pf, params
        if best_params is None:
            continue
        oos = _bt(te, best_params, REALISTIC_COST_BPS)
        dollars = spread_trade_dollars(
            te["a"], te["b"], cost_bps_per_leg=REALISTIC_COST_BPS, capital=CAPITAL, **best_params
        )
        oos_wins.append(
            _OOSWin(
                profit_factor=oos.profit_factor,
                max_drawdown_pct=oos.max_drawdown_pct,
                sharpe_ratio=oos.sharpe_ratio,
                total_trades=oos.total_trades,
                trades=[_Trade(pnl=d) for d in dollars],
            )
        )
    if not oos_wins:
        return {"verdict": "FAIL", "reason": "no OOS windows produced trades"}

    # --- gate inputs (mirrors the canonical per-strategy _compute_gate_v2) --- #
    oos_pfs = [r.profit_factor for r in oos_wins if r.total_trades >= 1]
    total_oos_trades = sum(r.total_trades for r in oos_wins)
    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs) if oos_pfs else 0.0
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    wfo_consistency = classify_wfo_consistency(oos_pfs)

    # Trade-level risk metrics (the fix): capital-relative permutation-MC drawdown
    # and a Deflated Sharpe from the real per-trade return distribution, deflated by
    # the GLOBAL trial count.
    mc_95th_dd = trade_level_mc_95th_dd(oos_wins, initial_capital=CAPITAL)
    dsr = trade_level_dsr(
        oos_wins, n_grid_combos=max(global_trial_count, n_combos), initial_capital=CAPITAL
    )

    fixed_pfs = []
    for params in grid:
        m = _bt(al, params, REALISTIC_COST_BPS)
        if m.total_trades >= 5 and np.isfinite(m.profit_factor):
            fixed_pfs.append(m.profit_factor)
    fixed_min_pf = float(min(fixed_pfs)) if fixed_pfs else 0.0
    cost_via = "realistic" if fixed_pfs and min(fixed_pfs) > 1.0 else "none"
    cost_idx = COST_TIER_ORDER.index(cost_via) if cost_via in COST_TIER_ORDER else -1
    cost_passes = cost_idx >= COST_TIER_ORDER.index("realistic")

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )
    if core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    pbo_val = None
    if len(windows) >= 4 and n_combos >= 2:
        rows = []
        for win in windows:
            seg = al[(al.index >= win["tr_s"]) & (al.index <= win["te_e"])]
            rows.append(
                [
                    (m.profit_factor if np.isfinite(m.profit_factor) else 5.0)
                    for m in (_bt(seg, p, 0.0) for p in grid)
                ]
            )
        pf_matrix = np.asarray(rows, dtype=float)
        if pf_matrix.shape[0] >= 4:
            s = min(pf_matrix.shape[0] - (pf_matrix.shape[0] % 2), 10)
            if s >= 2:
                pbo_val = probability_of_backtest_overfitting(pf_matrix, n_partitions=s).pbo

    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6),
        "dsr_global": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": round(fixed_min_pf, 4),
        "cost_survives_through": cost_via,
        "n_oos_windows": len(oos_wins),
        "total_oos_trades": total_oos_trades,
        "pbo": pbo_val,
        "n_grid_combos": n_combos,
        "global_trial_count": global_trial_count,
    }


# --------------------------------------------------------------------------- #
# Runner: smoke -> gauntlet for every pair, logged to the same ResultsDB, with
# the DSR denominator fixed to the relval family's total parameterizations.
# --------------------------------------------------------------------------- #


def run_relval(
    pairs: list[Pair],
    timeframe: str,
    cache_dir: str | Path,
    db_path: str | Path,
    created_at: str,
) -> dict:
    """Run every cointegrated pair through smoke -> relval gauntlet at `timeframe`.

    Relative-value is its OWN multiple-testing family: the DSR `n_trials`
    denominator is the sum of parameterizations across the pairs that actually
    have data (not the directional factory's 660). Pairs missing a leg's cache
    are skipped before the count so the denominator isn't phantom-inflated.
    """
    db = ResultsDB(db_path)
    run_id = db.new_run(
        created_at,
        {"family": "relative_value", "timeframe": timeframe, "n_pairs": len(pairs)},
    )

    runnable = [
        p
        for p in pairs
        if has_cache(p.leg_a, timeframe, cache_dir) and has_cache(p.leg_b, timeframe, cache_dir)
    ]
    skipped = [p for p in pairs if p not in runnable]
    global_trials = sum(p.n_param_combos() for p in runnable)

    rows: list[dict] = []
    for p in skipped:
        rows.append({"pair": p.name, "stage": "skip", "reason": "missing leg cache"})

    for p in runnable:
        sym = f"{p.leg_a}/{p.leg_b}"
        cid = db.record_candidate(run_id, p.name, sym, timeframe, p.default_params, "smoke")
        bars_a = load_bars(p.leg_a, timeframe, cache_dir)
        bars_b = load_bars(p.leg_b, timeframe, cache_dir)
        n_overlap = len(_aligned(bars_a, bars_b))

        survives, sm = smoke_test_pair(p, bars_a, bars_b, timeframe)
        sm["n_overlap_bars"] = n_overlap
        db.record_result(
            cid,
            "smoke",
            sm,
            verdict="PASS" if survives else "KILL",
            kill_reason=sm.get("kill_reason"),
        )
        row = {"pair": p.name, "sym": sym, "tf": timeframe, "smoke": sm, "smoke_pass": survives}
        if not survives:
            row["stage"] = "killed_smoke"
            rows.append(row)
            continue

        gate = relval_gauntlet(p, bars_a, bars_b, timeframe, global_trials)
        verdict = gate.get("verdict", "FAIL")
        db.record_result(cid, "robustness", gate, verdict=verdict)
        row["stage"] = "robustness"
        row["gate"] = gate
        row["verdict"] = verdict
        rows.append(row)

    summary = {
        "run_id": run_id,
        "created_at": created_at,
        "timeframe": timeframe,
        "global_trials": global_trials,
        "n_pairs": len(runnable),
        "n_skipped_no_cache": len(skipped),
        "n_smoke_pass": sum(1 for r in rows if r.get("smoke_pass")),
        "n_robustness_pass": sum(1 for r in rows if r.get("verdict") == "PASS"),
        "rows": rows,
    }
    db.close()
    return summary


def render_relval_report(summary: dict) -> str:
    """Markdown report mirroring the directional factory's render_report."""
    s = summary
    lines = [
        "# Strategy-Factory Report -- Relative Value (pairs)",
        "",
        f"- Run ID: `{s['run_id']}`  |  Created: {s['created_at']}  |  TF: {s['timeframe']}",
        f"- Pairs screened: **{s['n_pairs']}**  "
        f"(global DSR n_trials = **{s['global_trials']}** parameterizations)"
        + (
            f"  |  skipped (no cache): {s['n_skipped_no_cache']}"
            if s.get("n_skipped_no_cache")
            else ""
        ),
        f"- Smoke survivors: **{s['n_smoke_pass']}**  |  "
        f"Robustness PASS: **{s['n_robustness_pass']}**",
        "",
    ]
    ran = [r for r in s["rows"] if r.get("stage") != "skip"]
    survivors = [r for r in ran if r.get("verdict") == "PASS"]

    lines += ["## Survivors (robustness PASS -> forward-shadow candidates)", ""]
    if survivors:
        for r in survivors:
            g = r.get("gate", {})
            lines.append(
                f"- **{r['pair']} ({r['sym']}) {r['tf']}** via {g.get('passed_via', '?')} "
                f"| pf_ci_lower {_fmt(g.get('pf_ci_lower'))} | dsr {_fmt(g.get('dsr'))} "
                f"| dsr_global {_fmt(g.get('dsr_global'))} | PBO {_fmt(g.get('pbo'))} "
                f"| mc_dd {_fmt(g.get('mc_95th_dd_pct'))}%"
            )
    else:
        lines.append("_None. No pair cleared gate-v2 after PBO + global DSR._")

    tested = [r for r in ran if r.get("smoke_pass")]
    lines += [
        "",
        "## Robustness-tested (smoke survivors)",
        "",
        "| Pair | Legs | TF | Verdict | pf_ci | mc_dd% | dsr | dsr_global | PBO |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in tested:
        g = r.get("gate", {}) or {}
        lines.append(
            f"| {r['pair']} | {r['sym']} | {r['tf']} | {r.get('verdict', '-')} "
            f"| {_fmt(g.get('pf_ci_lower'))} | {_fmt(g.get('mc_95th_dd_pct'))} "
            f"| {_fmt(g.get('dsr'))} | {_fmt(g.get('dsr_global'))} | {_fmt(g.get('pbo'))} |"
        )
    if not tested:
        lines.append("| _none_ | | | | | | | | |")

    lines += ["", "## Kill / fail reasons", ""]
    for r in ran:
        if r.get("verdict") == "PASS":
            continue
        if not r.get("smoke_pass"):
            sm = r.get("smoke", {}) or {}
            reason = sm.get("kill_reason") or "below smoke floor"
            extra = (
                f" (pre_pf {_fmt(sm.get('pre_pf'))}, trades {sm.get('trades')}, "
                f"overlap {sm.get('n_overlap_bars')})"
            )
            lines.append(f"- **{r['pair']} {r['tf']}** -- smoke KILL: {reason}{extra}")
        else:
            g = r.get("gate", {}) or {}
            reason = g.get("reason") or _gate_fail_reason(g)
            lines.append(f"- **{r['pair']} {r['tf']}** -- robustness {r.get('verdict')}: {reason}")

    skips = [r for r in s["rows"] if r.get("stage") == "skip"]
    if skips:
        names = sorted({r["pair"] for r in skips})
        lines += ["", "## Coverage gaps (no cache)", "", f"Skipped pairs: {', '.join(names)}"]
    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)


def _gate_fail_reason(gate: dict) -> str:
    bits = []
    if gate.get("pf_ci_lower") is not None and gate["pf_ci_lower"] < 1.10:
        bits.append(f"pf_ci_lower {gate['pf_ci_lower']:.2f}<1.10")
    if gate.get("p_edge") is not None and gate["p_edge"] < 0.95:
        bits.append(f"p_edge {gate['p_edge']:.2f}<0.95")
    dd = gate.get("mc_95th_dd_pct", gate.get("mc_95th_dd"))
    if dd is not None and dd > 5.0:
        bits.append(f"mc_dd {dd:.1f}%>5%")
    if gate.get("dsr") is not None and gate["dsr"] < 0.10:
        bits.append(f"dsr {gate['dsr']:.2f}<0.10")
    if gate.get("pbo") is not None and gate["pbo"] > 0.5:
        bits.append(f"PBO {gate['pbo']:.2f}>0.5 (overfit)")
    return "; ".join(bits) if bits else "did not clear gate-v2 core or ALT"
