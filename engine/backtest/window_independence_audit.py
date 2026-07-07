"""OOS-window independence / overlap audit for gate-v2 walk-forward candidates.

Read-only analysis. For each candidate verdict JSON it measures whether the
per-window OOS records that feed the family-FDR binomial test are actually
*independent* — because the BH-FDR "more windows -> cross the line" thesis is
invalid when adjacent OOS windows overlap (step < test) or when windows are
degenerate (1-2 trades, no losers -> PF = inf), both of which make the binomial
p-values anti-conservative.

Per candidate it reports:
  - calendar overlap of adjacent OOS windows (from wfo_config step vs test)
  - lag-1 autocorrelation of the per-window OOS PF series
  - effective independent-N (N_eff): block (test/step) and AR(1)
  - per-window OOS trade counts + thin-window (<MIN_OOS_TRADES_PER_WINDOW) count
  - best-case binomial p at nominal vs effective N, vs a BH reference line

No writes; stdlib only. Default verdict dir is the repo gate_v2_verdicts store;
override with --verdict-dir. Pass candidate labels as positional args, or none
to audit a built-in shortlist.

Usage:
    python -m backtest.window_independence_audit \
        MGC_singlefinder_fill_rank1 MGC_trend_rank4
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from math import comb
from pathlib import Path

# Default verdict store, relative to this file (engine/backtest/ -> engine/data/...).
_DEFAULT_VERDICT_DIR = Path(__file__).resolve().parents[1] / "data" / "gate_v2_verdicts"

# Mirror engine/backtest/_gate_v2_helpers.py MIN_OOS_TRADES_PER_WINDOW.
MIN_OOS_TRADES_PER_WINDOW = 5
BH_ALPHA = 0.05

_DEFAULT_SHORTLIST = [
    "MGC_singlefinder_fill_rank1",
    "MGC_trend_rv_filter_rank1",
    "MGC_trend_rank4",
    "MGC_trend_adx_filter_rank1",
]


def _parse_ym(s: str) -> int:
    """'2025-03' -> ordinal month index (year*12 + month)."""
    y, m = s.strip().split("-")
    return int(y) * 12 + int(m)


def _oos_bounds(period: str) -> tuple[int, int]:
    """'2025-01 -> 2025-03' -> (start_ord, end_ord) in ordinal months."""
    a, b = (p.strip() for p in period.split("->"))
    return _parse_ym(a), _parse_ym(b)


def _lag1_autocorr(x: list[float]) -> float:
    """Lag-1 autocorrelation; NaN if <3 points, zero variance, or non-finite."""
    if len(x) < 3 or any(not math.isfinite(v) for v in x):
        return float("nan")
    mu = st.mean(x)
    denom = sum((v - mu) ** 2 for v in x)
    if denom == 0:
        return float("nan")
    num = sum((x[i] - mu) * (x[i + 1] - mu) for i in range(len(x) - 1))
    return num / denom


def _neff_ar1(n: int, r: float) -> float:
    """AR(1) effective sample size; clamp r to [0, 1) for the variance-inflation form."""
    if math.isnan(r):
        return float(n)
    rr = max(0.0, min(r, 0.999))
    return n * (1 - rr) / (1 + rr)


def _binom_p_at_least(k: int, n: int, p: float = 0.5) -> float:
    """One-sided P(X >= k) for Binomial(n, p)."""
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def audit_candidate(name: str, verdict_dir: Path) -> dict:
    """Compute the independence/degeneracy metrics for one candidate verdict."""
    data = json.loads((verdict_dir / f"{name}.json").read_text())
    cfg = data.get("wfo_config", {})
    test_m = cfg.get("test_months")
    step_m = cfg.get("step_months")
    windows = data.get("windows", [])
    n = len(windows)

    pf = [w["oos_pf"] for w in windows if w.get("oos_pf") is not None]
    trades = [w.get("oos_trades", 0) for w in windows]
    wins = sum(1 for v in pf if v > 1.0)

    overlaps = []
    for i in range(len(windows) - 1):
        try:
            s0, e0 = _oos_bounds(windows[i]["oos_period"])
            s1, _e1 = _oos_bounds(windows[i + 1]["oos_period"])
            span = e0 - s0
            if span:
                overlaps.append(max(0, e0 - s1) / span)
        except (KeyError, ValueError, AttributeError):
            pass
    overlap_pct = 100 * st.mean(overlaps) if overlaps else 0.0

    ac1 = _lag1_autocorr(pf)
    block = (test_m / step_m) if (test_m and step_m) else 1.0
    neff_block = n / block if block else float(n)
    neff_ar = _neff_ar1(n, ac1)
    thin = sum(1 for t in trades if t < MIN_OOS_TRADES_PER_WINDOW)

    return {
        "name": name,
        "n": n,
        "wins": wins,
        "step_m": step_m,
        "test_m": test_m,
        "overlap_pct": overlap_pct,
        "ac1": ac1,
        "neff_block": neff_block,
        "neff_ar": neff_ar,
        "trades": trades,
        "median_trades": st.median(trades) if trades else 0,
        "thin": thin,
        "pf": pf,
        "degenerate": any(not math.isfinite(v) for v in pf),
    }


def _print_report(rows: list[dict], m_family: int) -> None:
    print(
        f"{'candidate':<32} {'N':>3} {'wins':>4} {'st/test':>7} {'ovlp%':>6} "
        f"{'AC1':>7} {'Neff_b':>7} {'Neff_ar':>7} {'medTr':>6} {'thin':>6}"
    )
    print("-" * 100)
    for r in rows:
        st_ratio = f"{r['step_m']}/{r['test_m']}" if r["step_m"] else "?"
        ac1 = "  inf/nan" if math.isnan(r["ac1"]) else f"{r['ac1']:>7.3f}"
        print(
            f"{r['name']:<32} {r['n']:>3} {r['wins']:>4} {st_ratio:>7} "
            f"{r['overlap_pct']:>5.0f}% {ac1} {r['neff_block']:>7.1f} "
            f"{r['neff_ar']:>7.1f} {r['median_trades']:>6} "
            f"{r['thin']:>3}/{r['n']:<2}"
        )

    bh_line = BH_ALPHA / m_family
    print()
    print("Best-case binomial p (all windows win, p0=0.5) at nominal vs effective N:")
    print(f"  BH reference line (rank-1, {m_family}-member family) = {bh_line:.5f}")
    print(f"{'candidate':<32} {'p(N)':>10} {'p(Neff_blk)':>12} {'p(Neff_ar1)':>12}")
    print("-" * 70)
    for r in rows:
        nb = max(1, round(r["neff_block"]))
        na = max(1, round(r["neff_ar"]))
        print(
            f"{r['name']:<32} {_binom_p_at_least(r['n'], r['n']):>10.5f} "
            f"{_binom_p_at_least(nb, nb):>12.5f} {_binom_p_at_least(na, na):>12.5f}"
        )

    print()
    print("Per-window OOS trade counts (degeneracy check):")
    for r in rows:
        deg = " [DEGENERATE: non-finite PF present]" if r["degenerate"] else ""
        print(f"  {r['name']:<32} {r['trades']}  median={r['median_trades']}{deg}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidates", nargs="*", help="verdict labels (default: built-in shortlist)")
    ap.add_argument("--verdict-dir", type=Path, default=_DEFAULT_VERDICT_DIR)
    args = ap.parse_args()

    names = args.candidates or _DEFAULT_SHORTLIST
    rows = [audit_candidate(name, args.verdict_dir) for name in names]
    _print_report(rows, m_family=len(names))


if __name__ == "__main__":
    main()
