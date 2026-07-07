"""ES-NQ relative-value (spread mean-reversion) backtester -- standalone + honest.

Hypothesis: MES and MNQ (both US equity-index futures) are cointegrated, so the
log-spread ln(ES) - ln(NQ) mean-reverts. Trade it market-neutral: when the spread
is stretched (|z| high) short the rich leg / long the cheap leg, exit on reversion,
hard-stop on divergence.

Design choices that keep it honest (NOT a grid-mined mirage):
  * Execution-agnostic return stream: a dollar-neutral +-$1 long/short book, so the
    measured edge is the spread's mean-reversion, independent of contract granularity.
  * No look-ahead: the z-score at bar t uses only data through bar t; the position it
    implies is HELD INTO bar t+1 (held = desired.shift(1)). Returns are earned on the
    held position.
  * FIXED sensible params (no per-window grid search) evaluated across rolling OOS
    windows -- grid-mining over a big param space is exactly what manufactures the
    small-sample mirages the family-FDR campaign keeps killing.
  * Realistic per-leg transaction cost in bps, charged on every position change, on
    BOTH legs.

Pure functions (compute_spread_z / generate_positions / run_backtest / compute_metrics)
are unit-tested in tests/test_spread_backtest.py. Read-only analysis; not on the
live trading path.

Usage (from engine/):
    .venv/Scripts/python -m backtest.spread_backtest --tf 1h
    .venv/Scripts/python -m backtest.spread_backtest --tf 1d --entry 2.0 --window 40
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

_CACHE = Path(__file__).resolve().parent / "cache"
# Canonical main-checkout cache (worktree caches are gitignored/empty).
_CANONICAL_CACHE = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache")


def _resolve_cache(cache_dir: Path | None) -> Path:
    """Prefer an explicit cache dir, else the local cache, else the canonical one."""
    for cand in (cache_dir, _CACHE, _CANONICAL_CACHE):
        if cand and cand.exists() and any(cand.glob("*.csv")):
            return cand
    return _CANONICAL_CACHE


# Matched MES/MNQ cache pairs (identical date ranges, aligned on join).
PAIRS = {
    "1h": ("MES_2024-04-26_2026-06-22_1h.csv", "MNQ_2024-04-26_2026-06-22_1h.csv"),
    "1d": ("MES_2022-01-01_2026-03-28_1d.csv", "MNQ_2022-01-01_2026-03-28_1d.csv"),
}

# Fixed, a-priori parameters (NOT grid-searched). z over a ~1-month-ish lookback,
# classic 2-sigma entry / revert-to-half-sigma exit / 4-sigma divergence stop.
DEFAULT_PARAMS = {"window": 40, "entry": 2.0, "exit": 0.5, "stop": 4.0}

# Conservative all-in per-leg cost (commission + ~1 tick slippage + half spread) in
# basis points of notional, charged whenever that leg's position changes by 1 unit.
DEFAULT_COST_BPS_PER_LEG = 2.0


def compute_spread_z(
    close_a: np.ndarray, close_b: np.ndarray, window: int
) -> tuple[np.ndarray, np.ndarray]:
    """Log-spread ln(a)-ln(b) and its trailing-window z-score (no look-ahead).

    z[t] uses the rolling mean/std over the window ENDING AT t (inclusive of t, which
    is known at t's close). First window-1 points are NaN; zero-variance windows -> 0.
    """
    a = np.asarray(close_a, dtype=float)
    b = np.asarray(close_b, dtype=float)
    spread = np.log(a) - np.log(b)
    s = pd.Series(spread)
    mean = s.rolling(window).mean()
    std = s.rolling(window).std(ddof=0)
    z = (s - mean) / std
    z = z.where(std > 0, 0.0)  # zero-variance window -> z = 0, not inf
    # keep the NaN warm-up (first window-1) as NaN so signals stay flat there.
    # rolling mean is NaN exactly during warm-up (min_periods defaults to window).
    z = z.mask(mean.isna(), np.nan)
    return spread, z.to_numpy()


def step_position(cur: int, z: float, entry: float, exit_: float, stop: float) -> int:
    """One-bar spread-position update -- the primitive shared by the batch backtest and
    the live/forward dark track (single source of truth).

    +1 = long spread (long ES / short NQ), -1 = short spread, 0 = flat. NaN z holds the
    current position; flat enters when |z|>entry (against the move = betting reversion);
    in-position exits when |z| reverts below exit_ OR diverges beyond stop. Pure.
    """
    if np.isnan(z):
        return cur
    if cur == 0:
        if z > entry:
            return -1  # spread rich -> expect fall -> short the spread
        if z < -entry:
            return 1  # spread cheap -> expect rise -> long the spread
        return 0
    if abs(z) < exit_ or abs(z) > stop:
        return 0
    return cur


def generate_positions(z: np.ndarray, entry: float, exit_: float, stop: float) -> np.ndarray:
    """Stateful spread position over a z series, via the per-bar `step_position` primitive.
    Returns the DESIRED position decided at each bar's close."""
    z = np.asarray(z, dtype=float)
    pos = np.zeros(len(z), dtype=int)
    cur = 0
    for t in range(len(z)):
        cur = step_position(cur, float(z[t]), entry, exit_, stop)
        pos[t] = cur
    return pos


def run_backtest(
    close_a: np.ndarray,
    close_b: np.ndarray,
    desired: np.ndarray,
    cost_bps_per_leg: float = DEFAULT_COST_BPS_PER_LEG,
) -> np.ndarray:
    """Net per-bar return of the dollar-neutral spread book.

    held[t] = desired[t-1] (position decided at t-1 close, held through bar t). The
    +1 long-spread unit earns spread_ret[t] = dlog_a[t] - dlog_b[t]. Cost is charged
    when `held` changes, on both legs: |d(held)| * 2 legs * cost_bps.
    """
    a = np.asarray(close_a, dtype=float)
    b = np.asarray(close_b, dtype=float)
    desired = np.asarray(desired, dtype=float)
    dlog_a = np.diff(np.log(a), prepend=np.log(a[0]))
    dlog_b = np.diff(np.log(b), prepend=np.log(b[0]))
    spread_ret = dlog_a - dlog_b
    held = np.roll(desired, 1)
    held[0] = 0.0
    gross = held * spread_ret
    turn = np.abs(np.diff(held, prepend=0.0))
    cost = turn * 2.0 * (cost_bps_per_leg / 1e4)
    return gross - cost


def _trade_pnls(held: np.ndarray, net_ret: np.ndarray) -> list[float]:
    """Group net returns into per-trade P&Ls (a trade = a maximal run of constant
    nonzero held position)."""
    trades: list[float] = []
    cur_pos = 0.0
    acc = 0.0
    for h, r in zip(held, net_ret, strict=False):
        if h != cur_pos:
            if cur_pos != 0.0:
                trades.append(acc)
            acc = 0.0
            cur_pos = h
        if cur_pos != 0.0:
            acc += r
    if cur_pos != 0.0:
        trades.append(acc)
    return trades


def compute_metrics(net_ret: np.ndarray, desired: np.ndarray, periods_per_year: float) -> dict:
    """PF / Sharpe / maxDD / trade count / win rate on the net return stream."""
    net_ret = np.asarray(net_ret, dtype=float)
    held = np.roll(np.asarray(desired, dtype=float), 1)
    held[0] = 0.0
    trades = _trade_pnls(held, net_ret)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    mu, sd = float(np.mean(net_ret)), float(np.std(net_ret, ddof=0))
    sharpe = (mu / sd * np.sqrt(periods_per_year)) if sd > 0 else 0.0
    equity = np.cumsum(net_ret)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max(peak - equity)) if len(equity) else 0.0
    return {
        "pf": round(pf, 3) if np.isfinite(pf) else float("inf"),
        "sharpe": round(sharpe, 3),
        "total_return": round(float(np.sum(net_ret)), 4),
        "max_dd": round(max_dd, 4),
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
    }


def load_aligned(
    tf: str, cache_dir: Path | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inner-join the matched MES/MNQ caches on timestamp -> aligned close arrays."""
    fa, fb = PAIRS[tf]
    cache = _resolve_cache(cache_dir)
    da = pd.read_csv(cache / fa)[["timestamp", "close"]].rename(columns={"close": "a"})
    db = pd.read_csv(cache / fb)[["timestamp", "close"]].rename(columns={"close": "b"})
    m = da.merge(db, on="timestamp", how="inner").dropna().reset_index(drop=True)
    # Normalize to tz-naive so 1h (tz-aware) and 1d (tz-naive) compare consistently.
    dt = pd.to_datetime(m["timestamp"])
    if dt.dt.tz is not None:
        dt = dt.dt.tz_localize(None)
    ts = dt.to_numpy()
    return ts, m["a"].to_numpy(), m["b"].to_numpy()


def _periods_per_year(ts: np.ndarray) -> float:
    """Annualization factor from the median bar spacing."""
    if len(ts) < 3:
        return 252.0
    deltas = np.diff(ts).astype("timedelta64[s]").astype(float)
    med_s = float(np.median(deltas[deltas > 0]))
    year_s = 365.25 * 24 * 3600
    # markets aren't open 24/365; scale by ~0.7 trading-time fraction for intraday.
    frac = 1.0 if med_s >= 20 * 3600 else 0.7
    return max(1.0, (year_s / med_s) * frac)


def walk_forward(
    ts: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    params: dict,
    cost_bps: float,
    test_months: int = 3,
    step_months: int = 3,
    warmup_bars: int | None = None,
) -> list[dict]:
    """Rolling out-of-sample windows with FIXED params. Each window reports metrics on
    its own OOS slice; positions are generated on the full series (warmed up) and sliced,
    so no window peeks past its own end."""
    _, z = compute_spread_z(a, b, params["window"])
    desired = generate_positions(z, params["entry"], params["exit"], params["stop"])
    net = run_backtest(a, b, desired, cost_bps)
    ppy = _periods_per_year(ts)
    warmup = warmup_bars if warmup_bars is not None else params["window"]

    tsp = pd.to_datetime(ts)
    start = tsp.min().to_period("M").to_timestamp()
    end = tsp.max()
    out: list[dict] = []
    cur = start
    step = pd.DateOffset(months=step_months)
    test = pd.DateOffset(months=test_months)
    while cur + test <= end + pd.DateOffset(days=1):
        w_lo, w_hi = cur, cur + test
        mask = (tsp >= w_lo) & (tsp < w_hi)
        idx = np.where(mask)[0]
        # require warmup history before the window so the z-score is valid
        if len(idx) and idx[0] >= warmup:
            seg_net = net[idx]
            seg_des = desired[idx]
            m = compute_metrics(seg_net, seg_des, ppy)
            m["period"] = f"{w_lo:%Y-%m} -> {w_hi:%Y-%m}"
            out.append(m)
        cur = cur + step
    return out


def collect_oos_trades(
    ts: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    params: dict,
    cost_bps: float,
    test_months: int = 3,
    step_months: int = 3,
    warmup_bars: int | None = None,
) -> tuple[list[float], list[tuple[str, float]]]:
    """Pool the per-trade P&Ls across all OOS windows (for bootstrap), plus a list of
    (period, trade_pnl) tags so the trades can be split chronologically."""
    _, z = compute_spread_z(a, b, params["window"])
    desired = generate_positions(z, params["entry"], params["exit"], params["stop"])
    net = run_backtest(a, b, desired, cost_bps)
    held_full = np.roll(desired.astype(float), 1)
    held_full[0] = 0.0
    warmup = warmup_bars if warmup_bars is not None else params["window"]

    tsp = pd.to_datetime(ts)
    start = tsp.min().to_period("M").to_timestamp()
    end = tsp.max()
    pooled: list[float] = []
    tagged: list[tuple[str, float]] = []
    cur = start
    step = pd.DateOffset(months=step_months)
    test = pd.DateOffset(months=test_months)
    while cur + test <= end + pd.DateOffset(days=1):
        w_lo, w_hi = cur, cur + test
        idx = np.where((tsp >= w_lo) & (tsp < w_hi))[0]
        if len(idx) and idx[0] >= warmup:
            tr = _trade_pnls(held_full[idx], net[idx])
            tag = f"{w_lo:%Y-%m}"
            pooled.extend(tr)
            tagged.extend((tag, t) for t in tr)
        cur = cur + step
    return pooled, tagged


def _pf(pnls) -> float:
    pnls = np.asarray(pnls, dtype=float)
    gw = pnls[pnls > 0].sum()
    gl = -pnls[pnls < 0].sum()
    return (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)


def bootstrap_eval(pnls: list[float], n_boot: int = 5000, seed: int = 12345) -> dict:
    """Pooled-OOS per-trade bootstrap -> PF 5th-pct (pf_ci_lower) and p_edge = P(mean>0).

    This is the gate-v2-style read on whether the edge is real, independent of how the
    trades are split into windows. Deterministic via fixed seed."""
    arr = np.asarray(pnls, dtype=float)
    n = len(arr)
    if n < 2:
        return {"n_trades": n, "pf": 0.0, "pf_ci_lower": 0.0, "p_edge": 0.0, "mean": 0.0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    samples = arr[idx]
    pfs = np.array([_pf(s) for s in samples])
    finite = pfs[np.isfinite(pfs)]
    pf_ci_lower = float(np.percentile(finite, 5)) if len(finite) else float("inf")
    means = samples.mean(axis=1)
    p_edge = float((means > 0).mean())
    return {
        "n_trades": n,
        "pf": round(_pf(arr), 3),
        "pf_ci_lower": round(pf_ci_lower, 3),
        "p_edge": round(p_edge, 3),
        "mean": round(float(arr.mean()), 6),
    }


def _summarize(windows: list[dict]) -> dict:
    pfs = [w["pf"] for w in windows if np.isfinite(w["pf"])]
    trades = [w["n_trades"] for w in windows]
    wins = sum(1 for w in windows if w["pf"] > 1.0)
    total_oos = sum(trades)
    return {
        "n_windows": len(windows),
        "total_oos_trades": total_oos,
        "p_edge": round(wins / len(windows), 3) if windows else 0.0,
        "median_trades_per_window": int(np.median(trades)) if trades else 0,
        "mean_pf": round(float(np.mean(pfs)), 3) if pfs else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tf", choices=list(PAIRS), default="1h")
    ap.add_argument("--window", type=int, default=DEFAULT_PARAMS["window"])
    ap.add_argument("--entry", type=float, default=DEFAULT_PARAMS["entry"])
    ap.add_argument("--exit", type=float, default=DEFAULT_PARAMS["exit"])
    ap.add_argument("--stop", type=float, default=DEFAULT_PARAMS["stop"])
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS_PER_LEG)
    ap.add_argument("--cache-dir", type=str, default=None)
    args = ap.parse_args()
    params = {"window": args.window, "entry": args.entry, "exit": args.exit, "stop": args.stop}

    ts, a, b = load_aligned(args.tf, Path(args.cache_dir) if args.cache_dir else None)
    ppy = _periods_per_year(ts)
    print(
        f"[spread] MES-MNQ {args.tf} | {len(a)} aligned bars | ppy~{ppy:.0f} | params={params} | cost={args.cost_bps}bp/leg"
    )

    _, z = compute_spread_z(a, b, params["window"])
    desired = generate_positions(z, params["entry"], params["exit"], params["stop"])
    net = run_backtest(a, b, desired, args.cost_bps)
    full = compute_metrics(net, desired, ppy)
    print(f"\n=== FULL-SAMPLE ===\n{full}")

    windows = walk_forward(ts, a, b, params, args.cost_bps)
    print("\n=== WALK-FORWARD (fixed params, rolling OOS) ===")
    for w in windows:
        print(
            f"  {w['period']}: pf={w['pf']:.3f} trades={w['n_trades']:>3} wr={w['win_rate']:.2f} dd={w['max_dd']:.4f}"
        )
    print(f"\n=== SUMMARY ===\n{_summarize(windows)}")

    # Pooled-OOS bootstrap (the honest gate-v2-style read) + chronological split.
    pooled, tagged = collect_oos_trades(ts, a, b, params, args.cost_bps)
    ev = bootstrap_eval(pooled)
    print("\n=== POOLED-OOS BOOTSTRAP (gate-v2 read) ===")
    print(ev)
    if len(tagged) >= 4:
        half = len(tagged) // 2
        first = [t for _, t in tagged[:half]]
        second = [t for _, t in tagged[half:]]
        print("\n=== CHRONOLOGICAL SPLIT (concentration check) ===")
        print(
            f"  first-half  ({tagged[0][0]}..{tagged[half - 1][0]}): "
            f"n={len(first)} pf={_pf(first):.3f} sum={sum(first):.4f}"
        )
        print(
            f"  second-half ({tagged[half][0]}..{tagged[-1][0]}): "
            f"n={len(second)} pf={_pf(second):.3f} sum={sum(second):.4f}"
        )

    print("\n=== GATE-V2 THRESHOLDS ===")
    pf_ci = ev["pf_ci_lower"]
    pe = ev["p_edge"]
    print(f"  pf_ci_lower {pf_ci} (need >=1.10): {'PASS' if pf_ci >= 1.10 else 'FAIL'}")
    print(f"  p_edge      {pe} (need >=0.95):  {'PASS' if pe >= 0.95 else 'FAIL'}")
    print(
        f"  OOS trades  {ev['n_trades']} (need >=30): {'PASS' if ev['n_trades'] >= 30 else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
