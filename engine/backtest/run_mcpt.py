#!/usr/bin/env python
"""
Monte Carlo Permutation Test (MCPT) -- overfit / luck detector for JARVIS edges.

Two subcommands, two nulls:

  trades  -- operates on the realized per-trade PnLs in the DB (paper_trades).
            Emits BOTH (a) a sign-flip randomization p-value under H0 "no
            directional edge, outcomes symmetric" and (b) a bootstrap CI on
            profit factor / mean PnL. Cheap; runs in milliseconds.

  prices  -- the strong overfit test. Permutes the bar-to-bar log returns of the
            1h cache (preserving each bar's intrabar OHLC shape so ATR realism
            survives), rebuilds a synthetic series, re-runs the FIXED champion
            strategy, and p-values its profit factor:

                p = (1 + #{perm_PF >= observed_PF}) / (N + 1)

            This catches what the gate-v2 bootstrap cannot: a strategy that fit
            the in-sample price path rather than a real edge (the documented
            "pooled bootstrap passes non-stationary edges" failure mode). v1 is
            fixed-param (tests the champion); an optimization-aware variant
            (re-run the whole selection per permutation) is a deferred follow-on.

Usage (from the engine/ directory):

    .venv/Scripts/python -m backtest.run_mcpt trades  --db data/jarvis_trader.db --symbol MES
    .venv/Scripts/python -m backtest.run_mcpt prices --symbol MES   # needs the 1h cache
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

_OHLC = ["open", "high", "low", "close"]

# Point value ($/point) per instrument -- used to build the Backtester for the
# prices subcommand. Mirrors the per-runner MULTIPLIER constants.
MULTIPLIERS: dict[str, float] = {
    "MES": 5.0,
    "MNQ": 2.0,
    "MGC": 10.0,
    "MCL": 10.0,
    "M2K": 5.0,
}


# ---------------------------------------------------------------------------
# Pure statistical primitives
# ---------------------------------------------------------------------------


def profit_factor(pnls: np.ndarray | list[float]) -> float:
    """Gross profit / gross loss. inf when there are no losses, 0 when no wins."""
    a = np.asarray(pnls, dtype=float)
    gross_profit = float(a[a > 0].sum())
    gross_loss = float(-a[a < 0].sum())
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _pf_rowwise(matrix: np.ndarray) -> np.ndarray:
    """Profit factor across axis=1 for a (R, n) matrix of PnLs."""
    pos = np.where(matrix > 0, matrix, 0.0).sum(axis=1)
    neg = np.where(matrix < 0, -matrix, 0.0).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pf = np.where(neg > 0, pos / neg, np.inf)
    return pf


def signflip_test(
    pnls: np.ndarray | list[float], n_resamples: int = 10_000, seed: int = 42
) -> dict:
    """Sign-flip randomization test.

    Under H0 (no directional edge, trade outcomes symmetric about zero) each
    trade's PnL is equally likely to carry either sign. We randomly negate each
    trade's PnL ``n_resamples`` times and ask how often the permuted mean (and
    profit factor) meets or beats the observed value. The (1 + count)/(N + 1)
    form keeps the p-value unbiased and strictly positive.
    """
    a = np.asarray(pnls, dtype=float)
    n = len(a)
    obs_mean = float(np.mean(a)) if n else 0.0
    obs_pf = profit_factor(a)

    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_resamples, n))
    flipped = a[None, :] * signs

    perm_means = flipped.mean(axis=1)
    perm_pf = _pf_rowwise(flipped)

    p_mean = (1 + int(np.sum(perm_means >= obs_mean))) / (n_resamples + 1)
    p_pf = (1 + int(np.sum(perm_pf >= obs_pf))) / (n_resamples + 1)

    return {
        "observed_mean": obs_mean,
        "observed_pf": obs_pf,
        "p_value_mean": float(p_mean),
        "p_value_pf": float(p_pf),
        "n_resamples": n_resamples,
        "n_trades": n,
    }


def bootstrap_test(
    pnls: np.ndarray | list[float],
    n_resamples: int = 10_000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict:
    """Bootstrap (resample-with-replacement) CI on profit factor and mean PnL.

    Complements the sign-flip test: instead of a permutation null it builds the
    sampling distribution of the metrics. ``p_value_pf_le_1`` is the bootstrap
    probability the edge is non-existent (PF <= 1.0); ``p_value_mean_le_0`` the
    analogue for mean PnL.
    """
    a = np.asarray(pnls, dtype=float)
    n = len(a)
    obs_mean = float(np.mean(a)) if n else 0.0
    obs_pf = profit_factor(a)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_resamples, n))
    samples = a[idx]

    boot_means = samples.mean(axis=1)
    boot_pf = _pf_rowwise(samples)

    lo_pct = 100.0 * (alpha / 2.0)
    hi_pct = 100.0 * (1.0 - alpha / 2.0)

    # PF can be +inf (a resample with no losing trades). Use nearest-rank
    # percentiles for the PF bounds so the result is always a real datum
    # (finite or a clean inf) -- linear interpolation between two infs yields nan.
    return {
        "observed_pf": obs_pf,
        "observed_mean": obs_mean,
        "pf_ci_lower": float(np.percentile(boot_pf, lo_pct, method="nearest")),
        "pf_ci_upper": float(np.percentile(boot_pf, hi_pct, method="nearest")),
        "mean_ci_lower": float(np.percentile(boot_means, lo_pct)),
        "mean_ci_upper": float(np.percentile(boot_means, hi_pct)),
        "p_value_pf_le_1": float(np.mean(boot_pf <= 1.0)),
        "p_value_mean_le_0": float(np.mean(boot_means <= 0.0)),
        "n_resamples": n_resamples,
        "n_trades": n,
    }


def permute_ohlc(df: pd.DataFrame, seed: int = 42, start_index: int = 1) -> pd.DataFrame:
    """Bar-return permutation that preserves intrabar OHLC structure.

    Decompose each bar (for index >= ``start_index``) into a log-space overnight
    gap (open vs. previous close) and an intrabar bundle (high/low/close offsets
    relative to the bar's own open). Permute the gaps with one permutation and
    the intrabar bundles with a second, then reconstruct a synthetic series from
    the real anchor bar. Keeping the intrabar bundle together guarantees the
    synthetic bars stay valid (high >= open/close >= low). Because the sum of
    gaps and the sum of intrabar close-offsets are permutation-invariant, the
    synthetic series ends at the same final close as the original.
    """
    log = np.log(df[_OHLC].to_numpy(dtype=float))
    lo, lh, ll, lc = log[:, 0], log[:, 1], log[:, 2], log[:, 3]
    n = len(df)
    m = n - start_index

    gap = lo[start_index:] - lc[start_index - 1 : n - 1]
    h_off = lh[start_index:] - lo[start_index:]
    l_off = ll[start_index:] - lo[start_index:]
    c_off = lc[start_index:] - lo[start_index:]

    rng = np.random.default_rng(seed)
    perm_gap = rng.permutation(m)
    perm_bar = rng.permutation(m)

    gap_p = gap[perm_gap]
    h_p, l_p, c_p = h_off[perm_bar], l_off[perm_bar], c_off[perm_bar]

    new_lc = np.empty(n)
    new_lo = np.empty(n)
    new_lh = np.empty(n)
    new_ll = np.empty(n)
    new_lc[:start_index] = lc[:start_index]
    new_lo[:start_index] = lo[:start_index]
    new_lh[:start_index] = lh[:start_index]
    new_ll[:start_index] = ll[:start_index]

    # close[i] = close[i-1] + gap[i] + c_off[i]  -> cumulative sum of per-bar steps
    step = gap_p + c_p
    new_lc[start_index:] = lc[start_index - 1] + np.cumsum(step)

    prev_close = np.empty(m)
    prev_close[0] = lc[start_index - 1]
    prev_close[1:] = new_lc[start_index : n - 1]

    new_lo[start_index:] = prev_close + gap_p
    new_lh[start_index:] = new_lo[start_index:] + h_p
    new_ll[start_index:] = new_lo[start_index:] + l_p

    out = np.exp(np.column_stack([new_lo, new_lh, new_ll, new_lc]))
    return pd.DataFrame(out, columns=_OHLC, index=df.index)


def prices_mcpt(
    df: pd.DataFrame,
    run_fn: Callable[[pd.DataFrame], object],
    n_resamples: int = 200,
    seed: int = 42,
) -> dict:
    """Prices-MCPT: re-run ``run_fn`` on permuted price series, p-value its PF.

    ``run_fn`` takes an OHLC DataFrame and returns an object exposing
    ``profit_factor``. The observed PF is computed on the real series; each
    permutation gets a distinct seed so the run is reproducible yet varied.
    """
    observed_pf = float(run_fn(df).profit_factor)

    perm_pfs = np.empty(n_resamples)
    for i in range(n_resamples):
        permuted = permute_ohlc(df, seed=seed + i + 1)
        perm_pfs[i] = float(run_fn(permuted).profit_factor)

    count_ge = int(np.sum(perm_pfs >= observed_pf))
    p_value = (1 + count_ge) / (n_resamples + 1)

    return {
        "observed_pf": observed_pf,
        "p_value": float(p_value),
        "count_ge_observed": count_ge,
        "n_resamples": n_resamples,
        "perm_pf_mean": float(np.mean(perm_pfs)),
        "perm_pf_50th": float(np.percentile(perm_pfs, 50)),
        "perm_pf_95th": float(np.percentile(perm_pfs, 95)),
    }


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_trade_pnls(db_path: str, symbol: str) -> np.ndarray:
    """Realized per-trade PnLs for ``symbol`` from the paper_trades table.

    Excludes rows with NULL pnl (open / unfilled trades).
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT pnl FROM paper_trades WHERE symbol = ? AND pnl IS NOT NULL",
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    return np.array([r[0] for r in rows], dtype=float)


def _load_ohlc_csv(path: Path) -> pd.DataFrame:
    """Load an IBKR cache CSV into a lowercase-column OHLC frame (datetime index)."""
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    missing = set(_OHLC) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    return df[_OHLC]


def _make_strategy_run_fn(symbol: str, params: dict, multiplier: float) -> Callable:
    """Build a fixed-param champion run_fn for the prices subcommand."""
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    def run_fn(df: pd.DataFrame):
        df_sig = generate_sma_trend_signals(
            df,
            fast=params["fast"],
            slow=params["slow"],
            atr_trail_mult=params["atr_trail_mult"],
            min_rv_annualized=0.0,
        )
        bt = Backtester(
            initial_capital=50_000.0,
            risk_per_trade=0.01,
            max_daily_loss=0.02,
            max_drawdown=0.05,
            t1_exit_pct=0.50,
            t2_exit_pct=0.30,
            commission_per_contract=0.62,
            slippage_ticks=2.0,
        )
        return bt.run(df_sig, symbol=symbol, multiplier=multiplier)

    return run_fn


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_trades(args) -> int:
    pnls = load_trade_pnls(args.db, args.symbol)
    n = len(pnls)
    print(f"\n=== TRADES MCPT -- {args.symbol} ===")
    print(f"Source: {args.db} (paper_trades)")
    print(f"Trades: {n}")
    if n < 2:
        print("INSUFFICIENT_DATA: need >= 2 closed trades.")
        return 1
    if n < 30:
        print(f"[CAUTION] small sample (n={n} < 30) -- p-values/CI are wide; treat as indicative.")

    sf = signflip_test(pnls, n_resamples=args.n, seed=args.seed)
    bs = bootstrap_test(pnls, n_resamples=args.n, seed=args.seed)

    print("\n-- sign-flip randomization (H0: no directional edge) --")
    print(f"  observed mean PnL : ${sf['observed_mean']:,.2f}")
    print(f"  observed PF       : {sf['observed_pf']:.3f}")
    print(f"  p(mean)           : {sf['p_value_mean']:.4f}")
    print(f"  p(PF)             : {sf['p_value_pf']:.4f}")
    print("\n-- bootstrap CI (resample with replacement) --")
    print(f"  PF 95% CI         : [{bs['pf_ci_lower']:.3f}, {bs['pf_ci_upper']:.3f}]")
    print(f"  mean 95% CI       : [${bs['mean_ci_lower']:,.2f}, ${bs['mean_ci_upper']:,.2f}]")
    print(f"  P(PF <= 1.0)      : {bs['p_value_pf_le_1']:.4f}")
    print(f"  P(mean <= 0)      : {bs['p_value_mean_le_0']:.4f}")

    significant = sf["p_value_mean"] < 0.05 and bs["p_value_pf_le_1"] < 0.05
    print(f"\nVERDICT: {'EDGE PLAUSIBLE (p<0.05 both)' if significant else 'NOT SIGNIFICANT'}")
    return 0


def _cmd_prices(args) -> int:
    from backtest._gate_v2_helpers import _find_latest_cache
    from backtest.trend_signals import get_sma_trend_params

    sym = args.symbol.upper()
    cache_dir = Path(args.cache_dir)
    data_file = _find_latest_cache(cache_dir, sym, suffix=f"_{args.interval}.csv")
    df = _load_ohlc_csv(data_file)

    params = get_sma_trend_params(sym)
    if params is None:
        print(f"ERROR: no SMA_TREND_PARAMS champion for {sym}.")
        return 1
    multiplier = MULTIPLIERS.get(sym)
    if multiplier is None:
        print(f"ERROR: no multiplier registered for {sym}; add it to MULTIPLIERS.")
        return 1

    print(f"\n=== PRICES MCPT -- {sym} {args.interval} ===")
    print(f"Cache: {data_file.name} ({len(df)} bars)")
    print(
        f"Champion: fast={params['fast']} slow={params['slow']} "
        f"atr_trail_mult={params['atr_trail_mult']} | multiplier=${multiplier}"
    )
    print(f"Permutations: {args.n} (re-running fixed-param champion on each)")

    run_fn = _make_strategy_run_fn(sym, params, multiplier)
    res = prices_mcpt(df, run_fn, n_resamples=args.n, seed=args.seed)

    print(f"\n  observed PF       : {res['observed_pf']:.3f}")
    print(f"  permuted PF 50th  : {res['perm_pf_50th']:.3f}")
    print(f"  permuted PF 95th  : {res['perm_pf_95th']:.3f}")
    print(f"  perms >= observed : {res['count_ge_observed']} / {res['n_resamples']}")
    print(f"  p-value           : {res['p_value']:.4f}")
    print(
        f"\nVERDICT: {'EDGE PLAUSIBLE (p<0.05)' if res['p_value'] < 0.05 else 'NOT SIGNIFICANT -- consistent with overfit/luck'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monte Carlo Permutation Test for JARVIS strategy edges."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tr = sub.add_parser("trades", help="sign-flip + bootstrap on realized DB trade PnLs")
    p_tr.add_argument("--db", required=True, help="path to jarvis_trader.db")
    p_tr.add_argument("--symbol", required=True)
    p_tr.add_argument("--n", type=int, default=10_000, help="resamples (default 10000)")
    p_tr.add_argument("--seed", type=int, default=42)
    p_tr.set_defaults(func=_cmd_trades)

    p_pr = sub.add_parser("prices", help="bar-permutation MCPT re-running the champion")
    p_pr.add_argument("--symbol", required=True)
    p_pr.add_argument("--n", type=int, default=200, help="permutations (default 200)")
    p_pr.add_argument("--seed", type=int, default=42)
    p_pr.add_argument("--interval", default="1h")
    p_pr.add_argument("--cache-dir", default="backtest/cache")
    p_pr.set_defaults(func=_cmd_prices)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
