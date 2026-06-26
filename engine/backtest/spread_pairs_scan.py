"""Relative-value spread scan across MULTIPLE cointegrated pairs.

ES-NQ (see `spread_backtest.py` / `data/spread_es_nq_results.md`) showed a genuine but
NON-STATIONARY edge (back-loaded into 2025-H2). Open question: is relative-value a viable
strategy CLASS for us, or was ES-NQ a one-off? This scan answers it by running the SAME
validated pipeline -- z-score signal, no-look-ahead, rolling-OOS WFO, pooled bootstrap,
and the mandatory chronological H1/H2 split -- across several pairs:

  * MES-M2K  (S&P 500 vs Russell 2000  -- large- vs small-cap, classic risk-on/off)
  * MNQ-M2K  (Nasdaq-100 vs Russell 2000)
  * ZN-ZB    (10Y vs 30Y Treasury -- the classic "NOB" curve spread; different asset class)

Reuses every pure function from `spread_backtest` (single source of truth); this module
only adds a generic pair loader + multi-pair orchestration. FIXED a-priori params (no
grid-mining). Read-only analysis; not on the live trading path.

Usage (from engine/):
    .venv/Scripts/python -m backtest.spread_pairs_scan
    .venv/Scripts/python -m backtest.spread_pairs_scan --cost-bps 4.0
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import spread_backtest as sb

# Named pairs -> (cache_file_a, cache_file_b, timeframe). Matched date ranges, aligned on join.
PAIRS_REG: dict[str, tuple[str, str, str]] = {
    "MES-M2K": ("MES_2024-04-26_2026-06-22_1h.csv", "M2K_2024-04-26_2026-06-22_1h.csv", "1h"),
    "MNQ-M2K": ("MNQ_2024-04-26_2026-06-22_1h.csv", "M2K_2024-04-26_2026-06-22_1h.csv", "1h"),
    "ZN-ZB": ("ZN_2025-06-18_2026-06-24_1h.csv", "ZB_2025-06-18_2026-06-24_1h.csv", "1h"),
}


def load_pair(
    file_a: str, file_b: str, cache_dir: Path | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inner-join two named caches on timestamp -> aligned (ts, close_a, close_b).
    tz-normalized so 1h (tz-aware) and 1d (tz-naive) compare consistently."""
    cache = sb._resolve_cache(cache_dir)
    da = pd.read_csv(cache / file_a)[["timestamp", "close"]].rename(columns={"close": "a"})
    db = pd.read_csv(cache / file_b)[["timestamp", "close"]].rename(columns={"close": "b"})
    m = da.merge(db, on="timestamp", how="inner").dropna().reset_index(drop=True)
    dt = pd.to_datetime(m["timestamp"])
    if dt.dt.tz is not None:
        dt = dt.dt.tz_localize(None)
    return dt.to_numpy(), m["a"].to_numpy(), m["b"].to_numpy()


def classify_verdict(
    pf_ci_lower: float, p_edge: float, n_trades: int, h1_sum: float | None, h2_sum: float | None
) -> tuple[bool, bool, str]:
    """Pure verdict logic -> (pooled_pass, stationary, verdict).

    pooled_pass = the three gate-v2 pooled thresholds. stationary = BOTH chronological
    halves profitable (the ES-NQ trap is a pooled PASS with all profit in one half).
    Only pooled_pass AND stationary earns CANDIDATE.
    """
    pooled_pass = pf_ci_lower >= 1.10 and p_edge >= 0.95 and n_trades >= 30
    stationary = bool(h1_sum is not None and h2_sum is not None and h1_sum > 0 and h2_sum > 0)
    if pooled_pass and stationary:
        verdict = "CANDIDATE"
    elif pooled_pass:
        verdict = "NON-STATIONARY"
    else:
        verdict = "NO_EDGE"
    return pooled_pass, stationary, verdict


def scan_pair(
    name: str,
    file_a: str,
    file_b: str,
    params: dict | None = None,
    cost_bps: float = sb.DEFAULT_COST_BPS_PER_LEG,
    cache_dir: Path | None = None,
) -> dict:
    """Run the full ES-NQ-equivalent analysis on one pair -> verdict dict.

    The chronological H1/H2 split is the load-bearing check: a pooled-bootstrap PASS with
    all profit in one half is the ES-NQ non-stationarity trap, not a deployable edge.
    """
    params = params or sb.DEFAULT_PARAMS
    ts, a, b = load_pair(file_a, file_b, cache_dir)
    windows = sb.walk_forward(ts, a, b, params, cost_bps)
    pooled, tagged = sb.collect_oos_trades(ts, a, b, params, cost_bps)
    ev = sb.bootstrap_eval(pooled)

    h1 = h2 = None
    if len(tagged) >= 4:
        half = len(tagged) // 2
        first = [t for _, t in tagged[:half]]
        second = [t for _, t in tagged[half:]]
        h1 = {"n": len(first), "pf": round(sb._pf(first), 3), "sum": round(sum(first), 4)}
        h2 = {"n": len(second), "pf": round(sb._pf(second), 3), "sum": round(sum(second), 4)}

    pooled_pass, stationary, verdict = classify_verdict(
        ev["pf_ci_lower"],
        ev["p_edge"],
        ev["n_trades"],
        h1["sum"] if h1 else None,
        h2["sum"] if h2 else None,
    )

    return {
        "pair": name,
        "n_bars": len(a),
        "n_windows": len(windows),
        "oos_trades": ev["n_trades"],
        "pf_ci_lower": ev["pf_ci_lower"],
        "p_edge": ev["p_edge"],
        "pooled_pass": pooled_pass,
        "h1": h1,
        "h2": h2,
        "stationary": stationary,
        "verdict": verdict,
    }


def _fmt(r: dict) -> str:
    h1 = r["h1"] or {}
    h2 = r["h2"] or {}
    return (
        f"{r['pair']:<8} | bars {r['n_bars']:>6} | win {r['n_windows']:>2} | OOS {r['oos_trades']:>4} | "
        f"pf_ci_lo {r['pf_ci_lower']:>5} | p_edge {r['p_edge']:>4} | "
        f"H1 pf {h1.get('pf', '-'):>6}/sum {h1.get('sum', '-'):>8} | "
        f"H2 pf {h2.get('pf', '-'):>6}/sum {h2.get('sum', '-'):>8} | {r['verdict']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cost-bps", type=float, default=sb.DEFAULT_COST_BPS_PER_LEG)
    args = ap.parse_args()
    print(f"[spread-pairs] params={sb.DEFAULT_PARAMS} cost={args.cost_bps}bp/leg\n")
    rows = []
    for name, (fa, fb, _tf) in PAIRS_REG.items():
        try:
            r = scan_pair(name, fa, fb, cost_bps=args.cost_bps)
        except Exception as e:  # noqa: BLE001 - report per-pair failure, keep scanning
            print(f"{name:<8} | ERROR: {e}")
            continue
        rows.append(r)
        print(_fmt(r))
    cands = [r["pair"] for r in rows if r["verdict"] == "CANDIDATE"]
    print(f"\nCANDIDATES (pooled PASS + both halves profitable): {cands or 'none'}")


if __name__ == "__main__":
    main()
