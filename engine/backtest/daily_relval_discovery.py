"""Standalone daily-ETF relative-value (pairs z-reversion) discovery screener.

The deep-data complement to the futures relative-value track. That track found two
survivors (ZB-ZN, M6E-M6B) but on a THIN basis -- the IB free-data ceiling leaves the
futures legs with only ~1yr of 1h bars. Cash ETFs carry DECADES of free daily history
(the same caches ``daily_calendar_discovery`` screens), so a daily-ETF pairs screen is
both (a) a properly-powered relative-value hunt and (b) frequency/window-compatible with
the calendar sleeves -- which makes a genuine CROSS-FAMILY book (market-neutral RV +
long-beta calendar, structurally uncorrelated) buildable on deep data later.

Each pair is a parameter-FREE z-reversion strategy (one pre-registered param set, no
per-pair tuning -> the only multiple-testing penalty is the number of PAIRS, exactly
like the calendar screener's per-effect penalty). Graded on the SAME honest bar via the
shared ``daily_calendar_discovery`` grader: bootstrap PF-CI, p_edge, deflated Sharpe
penalized for n_trials, max-DD, chronological H1/H2 stationarity, canonical gate-v2.

Pairs are economically motivated (cointegration has a STRUCTURAL driver -- a ratio that
mean-reverts for a reason), never data-mined. Liquid-ETF pairs are heavily arbitraged,
so a rigorous NULL here is the expected, honest baseline; survivors must clear the same
gate every other campaign edge does, and remain BLOCKED pending a forward shadow.

    .venv/Scripts/python -m backtest.daily_relval_discovery
    .venv/Scripts/python -m backtest.daily_relval_discovery --pairs GLD_SLV TLT_LQD
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# Reuse the EXACT honest-bar machinery the calendar screener uses (same worktree) so
# both screens grade on one identical bar -- no divergent re-implementation.
from backtest.daily_calendar_discovery import (
    CACHE_DIR,
    CAND_DSR,
    CAND_PF_CI,
    _latest_cache,
    grade,
)

# Pre-registered, parameter-free config (no per-pair tuning). Window ~ a quarter of
# trading days; 2-sigma entry / 0.5-sigma exit is the textbook pairs band; a wide 6-sigma
# stop only cuts genuinely-broken spreads. 1 bp/leg is the realistic cash-ETF cost tier.
WINDOW = 60
ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 6.0
COST_BPS_PER_LEG = 1.0

# Economically-motivated pairs over the deep daily ETF caches. Each spread has a
# structural reason to mean-revert; (name, leg_a, leg_b, rationale).
PAIRS: list[tuple[str, str, str, str]] = [
    ("GLD_SLV", "GLD", "SLV", "gold/silver ratio -- the oldest mean-reverting metals spread"),
    (
        "TLT_LQD",
        "TLT",
        "LQD",
        "Treasury duration vs IG credit -- the credit-spread component reverts",
    ),
    (
        "LQD_HYG",
        "LQD",
        "HYG",
        "IG vs high-yield credit -- quality spread reverts with risk appetite",
    ),
    ("SPY_QQQ", "SPY", "QQQ", "broad market vs tech -- style/growth premium oscillates"),
    ("SPY_IWM", "SPY", "IWM", "large vs small cap -- the size premium mean-reverts over cycles"),
    ("EEM_EFA", "EEM", "EFA", "emerging vs developed intl equity -- relative risk premium reverts"),
    (
        "XLU_TLT",
        "XLU",
        "TLT",
        "utilities (bond proxy) vs Treasuries -- rate-sensitivity convergence",
    ),
    ("SPY_EFA", "SPY", "EFA", "US vs developed-intl equity -- the US-premium swings, then reverts"),
    ("GLD_TLT", "GLD", "TLT", "two safe havens -- gold vs duration rotate but co-move long-run"),
    ("HYG_SPY", "HYG", "SPY", "credit vs equity risk -- both risk-on, the basis reverts"),
    ("DIA_SPY", "DIA", "SPY", "Dow vs S&P -- near-redundant large-cap control (expect a null)"),
]


# ── spread / z-reversion engine (look-ahead-safe) ────────────────────────────────
def zscore_spread(close_a: pd.Series, close_b: pd.Series, window: int = WINDOW) -> pd.Series:
    """Rolling z-score of the log-spread log(A)-log(B) over the shared date index.
    Rolling stats use data THROUGH the current bar only (no look-ahead)."""
    idx = close_a.index.intersection(close_b.index).sort_values()
    a = np.log(pd.to_numeric(close_a.reindex(idx)).astype(float))
    b = np.log(pd.to_numeric(close_b.reindex(idx)).astype(float))
    spread = a - b
    mu = spread.rolling(window).mean()
    sd = spread.rolling(window).std(ddof=1)
    z = (spread - mu) / sd.where(sd > 0)
    return pd.Series(z.to_numpy(), index=idx, name="z")


def spread_returns(
    close_a: pd.Series,
    close_b: pd.Series,
    *,
    window: int = WINDOW,
    entry_z: float = ENTRY_Z,
    exit_z: float = EXIT_Z,
    stop_z: float = STOP_Z,
    cost_bps_per_leg: float = COST_BPS_PER_LEG,
) -> pd.Series:
    """Daily net returns of a dollar-neutral z-reversion book on the pair, on the days
    the book is active (in position, or bearing a transition cost). Net of cost charged
    per position change (2 legs). No look-ahead: the position decided at close t is held
    over (t, t+1] and earns the spread's change to t+1."""
    idx = close_a.index.intersection(close_b.index).sort_values()
    a = np.log(pd.to_numeric(close_a.reindex(idx)).astype(float)).to_numpy()
    b = np.log(pd.to_numeric(close_b.reindex(idx)).astype(float)).to_numpy()
    spread = a - b
    n = len(idx)
    if n < window + 2:
        return pd.Series(dtype=float)

    s = pd.Series(spread, index=idx)
    mu = s.rolling(window).mean().to_numpy()
    sd = s.rolling(window).std(ddof=1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):  # early-window NaN/0 sd is masked
        z = np.where(sd > 0, (spread - mu) / sd, np.nan)

    pos = np.zeros(n)
    cur = 0.0
    for t in range(n):
        zt = z[t]
        if np.isnan(zt):
            cur = 0.0
        elif cur == 0.0:
            if zt >= entry_z:
                cur = -1.0  # spread rich -> short it
            elif zt <= -entry_z:
                cur = 1.0  # spread cheap -> long it
        elif abs(zt) <= exit_z or abs(zt) >= stop_z:
            cur = 0.0  # reverted (take profit) or blew through the stop
        pos[t] = cur

    dspread = np.diff(spread)  # dspread[t] = spread[t+1]-spread[t], realized at t+1
    pnl = pos[:-1] * dspread
    # cost to ESTABLISH the position held over (t, t+1], attributed to the t+1 return bar
    dpos = np.abs(np.diff(np.concatenate([[0.0], pos])))[:-1]
    cost = dpos * 2.0 * (cost_bps_per_leg / 1e4)
    net = pnl - cost

    dates = [str(d.date()) for d in idx[1:]]
    ser = pd.Series(net, index=dates)
    return ser[ser != 0.0]


# ── screen + rank (delegates grading to the shared honest bar) ────────────────────
def _close_series(df: pd.DataFrame) -> pd.Series:
    col = "timestamp" if "timestamp" in df.columns else "date"
    return pd.Series(
        pd.to_numeric(df["close"]).to_numpy(), index=pd.to_datetime(df[col])
    ).sort_index()


def screen(
    pair: tuple[str, str, str, str], df_a: pd.DataFrame, df_b: pd.DataFrame, *, n_trials: int
) -> dict:
    name, _leg_a, _leg_b, rationale = pair
    r = spread_returns(_close_series(df_a), _close_series(df_b))
    return {"pair": name, "rationale": rationale, **grade(r, n_grid_combos=n_trials)}


def rank(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (
            0 if r.get("is_candidate") else 1,
            -float(r.get("dsr", 0.0)),
            -float(r.get("pf_ci_lower", 0.0)),
        ),
    )


def run(pairs=PAIRS, *, cache_dir: Path = CACHE_DIR) -> list[dict]:
    n_trials = len(pairs)
    rows: list[dict] = []
    for pair in pairs:
        name, leg_a, leg_b, _ = pair
        pa, pb = _latest_cache(leg_a, cache_dir), _latest_cache(leg_b, cache_dir)
        if pa is None or pb is None:
            miss = leg_a if pa is None else leg_b
            print(f"  [skip] {name}: no _1d cache for {miss} under {cache_dir}")
            continue
        rows.append(screen(pair, pd.read_csv(pa), pd.read_csv(pb), n_trials=n_trials))
    ranked = rank(rows)
    print(
        f"\nDAILY ETF RELATIVE-VALUE SCREEN ({len(rows)} pairs, parameter-free "
        f"z-reversion W{WINDOW}/{ENTRY_Z}-in/{EXIT_Z}-out, net @ {COST_BPS_PER_LEG:.0f}bp/leg, "
        f"deflated for {n_trials} trials)\n"
    )
    print(
        f"{'pair':9} {'n':>5} {'PFci':>6} {'p_edge':>6} {'dsr':>6} {'shrp':>6} "
        f"{'DD%':>6} {'H1/H2':>11} {'cand':>4} {'gate'}"
    )
    for r in ranked:
        flag = "YES" if r.get("is_candidate") else ""
        h = f"{r['h1_pf']:.2f}/{r['h2_pf']:.2f}"
        print(
            f"{r['pair']:9} {r['n']:>5} {r['pf_ci_lower']:>6.3f} {r['p_edge']:>6.3f} "
            f"{r['dsr']:>6.3f} {r['sharpe']:>6.2f} {r['max_dd_pct']:>6.2f} {h:>11} "
            f"{flag:>4} {r['gate'].get('verdict')}"
        )
    cands = [r for r in ranked if r.get("is_candidate")]
    print(
        f"\n{len(cands)} durable candidate(s) (stationary + PFci>={CAND_PF_CI} + dsr>={CAND_DSR}); "
        "all BLOCKED pending forward evidence + Amo review."
    )
    return ranked


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="daily ETF relative-value discovery screen")
    ap.add_argument("--pairs", nargs="+", help="restrict to these pair names")
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    args = ap.parse_args()
    pairs = PAIRS if not args.pairs else [p for p in PAIRS if p[0] in set(args.pairs)]
    run(pairs, cache_dir=args.cache_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
