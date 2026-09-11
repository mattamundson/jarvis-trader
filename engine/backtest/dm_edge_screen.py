"""Diebold-Mariano edge-validation screen — research lane, paper-only.

Compares two strategies' per-window OOS performance (from gate_v2 verdict JSONs)
using the Diebold-Mariano (1995) test with the Harvey-Leybourne-Newberger (1997)
small-sample correction and Newey-West (Bartlett) HAC variance.

No engine integration. Offline analysis tool only.
Source spec: docs/research/SPEC_2026-09-04_Diebold_Mariano_edge_screen.md

Usage:
    python dm_edge_screen.py <verdict_a.json> <verdict_b.json> [--metric sharpe|pf]
        [--power 2|1] [--one-sided greater|less]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def load_oos_series(path: str, metric: str) -> tuple[list[str], list[float]]:
    """Extract aligned (oos_period, value) series from a gate_v2 verdict JSON."""
    d = json.loads(Path(path).read_text())
    windows = d.get("windows") or []
    periods, values = [], []
    for w in windows:
        per = w.get("oos_period")
        v = w.get(f"oos_{metric}")
        if per is None or v is None:
            continue
        # Skip infinite PF (no losing trades) -> use None marker handled by caller alignment
        if not math.isfinite(v):
            v = None
        periods.append(per)
        values.append(v)
    return periods, values


def align(a_periods, a_vals, b_periods, b_vals):
    """Inner-join on oos_period; drop windows where either side is None."""
    b_map = dict(zip(b_periods, b_vals, strict=True))
    keys = [p for p in a_periods if p in b_map]
    a = [v for p, v in zip(a_periods, a_vals, strict=True) if p in b_map]
    b = [b_map[p] for p in keys]
    keep = [(x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None]
    if not keep:
        return [], []
    ka, kb = zip(*keep, strict=True)
    return list(ka), list(kb)


def losses(vals: list[float], power: int) -> list[float]:
    """Loss = |e|^p. For OOS Sharpe/PF comparisons we treat the metric directly
    as a 'score' and use negative score as loss (higher score = better)."""
    return [(-(v)) ** power if power == 1 else (v) ** 2 * 0 + (0.0 - v) ** power for v in vals]


def dm_test(a_vals: list[float], b_vals: list[float], power: int = 2, h: int = 1) -> dict:
    """DM test on loss differential d_t = L_a - L_b (loss = -score, higher score = better).

    H0: E[d] = 0 (equal predictive accuracy).
    Positive DM => A better than B (B has higher loss); negative => A worse.
    """
    n = len(a_vals)
    if n < 3:
        return {"n": n, "dm": None, "p_two_sided": None, "note": "insufficient aligned windows (need >=3)"}
    if power == 2:
        d = [(-a) ** 2 - (-b) ** 2 for a, b in zip(a_vals, b_vals, strict=True)]
    else:
        d = [(-a) - (-b) for a, b in zip(a_vals, b_vals, strict=True)]
    dbar = sum(d) / n
    # Newey-West / Bartlett HAC variance with lag h-1
    max_lag = max(0, h - 1)
    gamma0 = sum((x - dbar) ** 2 for x in d) / n
    lr_var = gamma0
    for lag in range(1, max_lag + 1):
        gamma_lag = sum((d[i] - dbar) * (d[i - lag] - dbar) for i in range(lag, n)) / n
        lr_var += 2.0 * (1.0 - lag / (max_lag + 1)) * gamma_lag
    if lr_var <= 0:
        return {"n": n, "dm": None, "p_two_sided": None, "note": "zero loss-differential variance (identical series?)"}
    dm = dbar / math.sqrt(lr_var / n)
    # Harvey-Leybourne-Newberger small-sample correction
    hln_factor = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n) if n > h else 1.0
    dm_star = dm * hln_factor
    # Student-t p-value, n-1 dof (two-sided), computed via incomplete beta
    p = _t_sf_two_sided(abs(dm_star), n - 1)
    return {
        "n": n,
        "dbar": dbar,
        "dm": dm,
        "dm_hln": dm_star,
        "hln_factor": hln_factor,
        "p_two_sided": p,
        "loss_power": power,
        "horizon_h": h,
    }


def _t_sf_two_sided(t: float, dof: int) -> float:
    """Two-sided p-value for |t| under Student-t via regularized incomplete beta."""
    if t == 0 or dof <= 0:
        return 1.0
    x = dof / (dof + t * t)
    return _betainc(dof / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) via NR continued fraction (Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    tiny = 1e-30
    eps = 3e-9
    maxit = 200

    def betacf(aa: float, bb: float, xx: float) -> float:
        qab, qap, qam = aa + bb, aa + 1.0, aa - 1.0
        c = 1.0
        d = 1.0 - qab * xx / qap
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        h = d
        for m in range(1, maxit + 1):
            m2 = 2 * m
            num = m * (bb - m) * xx / ((qam + m2) * (aa + m2))
            d = 1.0 + num * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + num / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            h *= d * c
            num = -(aa + m) * (qab + m) * xx / ((aa + m2) * (qap + m2))
            d = 1.0 + num * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + num / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < eps:
                break
        return h

    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a
        return front * betacf(a, b, x)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / b
    return 1.0 - front * betacf(b, a, 1.0 - x)


def main() -> int:
    ap = argparse.ArgumentParser(description="Diebold-Mariano edge screen (research lane)")
    ap.add_argument("verdict_a")
    ap.add_argument("verdict_b")
    ap.add_argument("--metric", choices=["sharpe", "pf"], default="sharpe")
    ap.add_argument("--power", type=int, choices=[1, 2], default=2)
    ap.add_argument("--one-sided", choices=["greater", "less"], default=None)
    args = ap.parse_args()

    ap_periods, ap_vals = load_oos_series(args.verdict_a, args.metric)
    bp_periods, bp_vals = load_oos_series(args.verdict_b, args.metric)
    a, b = align(ap_periods, ap_vals, bp_periods, bp_vals)
    res = dm_test(a, b, power=args.power)
    out = {
        "a": Path(args.verdict_a).name,
        "b": Path(args.verdict_b).name,
        "metric": f"oos_{args.metric}",
        **res,
    }
    if out.get("p_two_sided") is not None and args.one_sided:
        p2 = out["p_two_sided"]
        # one-sided: halve the two-sided p when the sign matches the direction
        sign_ok = (out["dm_hln"] > 0) if args.one_sided == "greater" else (out["dm_hln"] < 0)
        out["p_one_sided"] = (p2 / 2.0) if sign_ok else (1.0 - p2 / 2.0)
        out["one_sided"] = args.one_sided
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
