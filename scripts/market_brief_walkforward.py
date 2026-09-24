#!/usr/bin/env python3
"""Walk-forward, no-lookahead calibration of the market-brief probability block.

Why this exists
---------------
Daily pre-registration accrues ONE scored observation per session, so it cannot answer the
only question that matters -- "does the state-matched model beat the naive base rate?" --
for months. This answers it today from existing history, WITHOUT weakening that discipline.

Mechanism
---------
For each session t, using ONLY sessions j <= t-1 (whose outcomes are already known):

  1. pool the realised outcomes of past sessions in the SAME state as t;
  2. emit that empirical distribution as the prediction for t -> t+1;
  3. score it against the actual outcome at t+1.

Nothing at or after t enters the prediction for t. The per-session features come from
market_brief_base_rates.build_records, which is already causal (each field for day i uses
only data available at day i's close). So this is a genuine out-of-sample walk-forward,
not an in-sample fit dressed up as one.

Baselines are scored on the SAME sessions (paired), which is the correct test: both arms
see identical regimes, so the difference is not confounded by drift.

  - trailing unconditional base rate (all past sessions, same no-lookahead window)
  - uniform 1/3

If the paired CI on (brier_base - brier_model) straddles zero, the conditional model is
NOT distinguishable from the base rate and should not be published as if it had edge.

Output: JSON + Markdown. Analysis only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_brief_base_rates as br

CLASSES = ("continuation", "rotation", "failure")
UNIFORM = {k: 1.0 / 3.0 for k in CLASSES}
SAFETY = {"mode": "ANALYSIS_ONLY", "orders_enabled": False, "risk_config_touched": False}
MODEL_VERSION = "market-brief-walkforward-v1"
MIN_TRAIN = 20      # matched-state sessions needed before trusting the conditional arm
WARMUP = 60         # sessions before the first prediction


def _counts(idxs: list[int], recs: list[dict[str, Any]], bars: list) -> dict[str, int]:
    c = {k: 0 for k in CLASSES}
    for j in idxs:
        nxt = bars[j + 1]
        c[br.label_partition(nxt.close, nxt.low, recs[j]["close"], recs[j]["low"])] += 1
    return c


def _probs(counts: dict[str, int], n: int) -> dict[str, float] | None:
    if n <= 0:
        return None
    c, r, f = br._class_rates(counts, n)
    return {"continuation": c / 100.0, "rotation": r / 100.0, "failure": f / 100.0}


def _brier(p: dict[str, float], realized: str) -> float:
    return sum((p[k] - (1.0 if realized == k else 0.0)) ** 2 for k in CLASSES)


def walk_forward(bars: list, vix_by_date: dict[str, float],
                 min_train: int = MIN_TRAIN, warmup: int = WARMUP) -> list[dict[str, Any]]:
    recs = br.build_records(bars, vix_by_date)
    rows: list[dict[str, Any]] = []
    for t in range(warmup, len(bars) - 1):
        state_t = recs[t]["state"]
        known = list(range(t))                      # j <= t-1: outcome known at t
        matched = [j for j in known if recs[j]["state"] == state_t]
        conditional = len(matched) >= min_train
        used = matched if conditional else known
        p_model = _probs(_counts(used, recs, bars), len(used))
        p_base = _probs(_counts(known, recs, bars), len(known))
        if p_model is None or p_base is None:
            continue
        nxt = bars[t + 1]
        realized = br.label_partition(nxt.close, nxt.low, recs[t]["close"], recs[t]["low"])
        rows.append({
            "date": recs[t]["date"], "state": state_t,
            "arm": "conditional" if conditional else "unconditional_fallback",
            "n_train": len(used), "n_matched": len(matched),
            "p_model": {k: round(p_model[k], 6) for k in CLASSES},
            "p_base": {k: round(p_base[k], 6) for k in CLASSES},
            "realized": realized,
            "top_pick": max(CLASSES, key=lambda k: p_model[k]),
            "brier_model": round(_brier(p_model, realized), 6),
            "brier_base": round(_brier(p_base, realized), 6),
            "brier_uniform": round(_brier(UNIFORM, realized), 6),
        })
    return rows


def _arm_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    bm = sum(r["brier_model"] for r in rows) / n
    bb = sum(r["brier_base"] for r in rows) / n
    bu = sum(r["brier_uniform"] for r in rows) / n
    diffs = [r["brier_base"] - r["brier_model"] for r in rows]   # >0 means model better
    mean_d = sum(diffs) / n
    sd = statistics.stdev(diffs) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    return {
        "n": n,
        "mean_brier_model": round(bm, 6),
        "mean_brier_base": round(bb, 6),
        "mean_brier_uniform": round(bu, 6),
        "paired_mean_diff_base_minus_model": round(mean_d, 6),
        "paired_ci95": [round(mean_d - 1.96 * se, 6), round(mean_d + 1.96 * se, 6)],
        "paired_se": round(se, 6),
        "paired_t": round(mean_d / se, 3) if se > 0 else None,
        "top_pick_hit_rate": round(100.0 * sum(1 for r in rows if r["top_pick"] == r["realized"]) / n, 1),
        "model_beats_base": (mean_d - 1.96 * se) > 0,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cond = [r for r in rows if r["arm"] == "conditional"]
    fall = [r for r in rows if r["arm"] == "unconditional_fallback"]
    per_state: dict[str, Any] = {}
    states = sorted({r["state"] for r in rows})
    for s in states:
        sub = [r for r in rows if r["state"] == s]
        per_state[s] = _arm_summary(sub)
    return {
        "all": _arm_summary(rows),
        "conditional_arm": _arm_summary(cond),
        "fallback_arm": _arm_summary(fall),
        "per_state": per_state,
    }


def render(payload: dict[str, Any]) -> str:
    a = payload["aggregate"]
    allS, condS = a["all"], a["conditional_arm"]
    L = []
    L.append("# Market Brief — Walk-Forward Calibration")
    L.append("")
    L.append(f"Generated: `{payload['generated_at']}`  ·  model `{MODEL_VERSION}`  ·  "
             f"lookback `{payload['lookback']}`")
    L.append("")
    L.append("No-lookahead walk-forward. At session *t* the prediction uses only sessions "
             "**≤ t−1** whose outcomes are already known; it is scored against the actual "
             "outcome of *t+1*. Baselines are scored on the identical sessions (paired).")
    L.append("")
    L.append("## Headline")
    L.append("")
    L.append(f"- Predictions scored: **{allS['n']}**")
    L.append(f"- Mean Brier — model **{allS['mean_brier_model']}**  ·  trailing base rate "
             f"**{allS['mean_brier_base']}**  ·  uniform **{allS['mean_brier_uniform']}**")
    L.append(f"- Paired difference (base − model): **{allS['paired_mean_diff_base_minus_model']}** "
             f"95% CI `{allS['paired_ci95']}`  (t={allS['paired_t']})")
    verdict = ("**model beats the base rate**" if allS["model_beats_base"]
               else "**NOT distinguishable from the base rate** (CI includes 0)")
    L.append(f"- Verdict: {verdict}")
    L.append(f"- Conditional arm: n={condS['n']} · mean Brier {condS.get('mean_brier_model')} "
             f"vs base {condS.get('mean_brier_base')} · paired CI `{condS.get('paired_ci95')}`")
    L.append(f"- Top-pick hit rate: **{allS['top_pick_hit_rate']}%**")
    L.append("")
    L.append("## Per state")
    L.append("")
    L.append("| state | n | Brier model | Brier base | paired diff | 95% CI | beats base |")
    L.append("|---|---:|---:|---:|---:|---|---|")
    for s, v in sorted(a["per_state"].items(), key=lambda kv: -kv[1].get("n", 0)):
        if not v.get("n"):
            continue
        L.append(f"| `{s}` | {v['n']} | {v['mean_brier_model']} | {v['mean_brier_base']} | "
                 f"{v['paired_mean_diff_base_minus_model']} | `{v['paired_ci95']}` | "
                 f"{'yes' if v['model_beats_base'] else 'no'} |")
    L.append("")
    L.append("## Reading this")
    L.append("")
    L.append("- A negative paired difference means the model is WORSE than the base rate.")
    L.append(f"- The conditional arm is engaged only when ≥{MIN_TRAIN} matched-state sessions "
             "precede the prediction; otherwise it falls back to the trailing unconditional rate.")
    L.append("- Brier is a proper score: lower is better. Uniform baseline = "
             f"{allS['mean_brier_uniform']}.")
    L.append("- Analysis only. No order routing, no risk configuration.")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", default=br.DEFAULT_LOOKBACK)
    ap.add_argument("--out-dir", default="docs/reports")
    ap.add_argument("--min-train", type=int, default=MIN_TRAIN)
    ap.add_argument("--warmup", type=int, default=WARMUP)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    es = br.fetch_daily("ES=F", a.lookback)
    vix = br.fetch_daily("^VIX", a.lookback)
    vix_by_date = {b.date: b.close for b in vix}
    rows = walk_forward(es, vix_by_date, min_train=a.min_train, warmup=a.warmup)
    payload = {
        "model_version": MODEL_VERSION, "safety": SAFETY,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lookback": a.lookback, "min_train": a.min_train, "warmup": a.warmup,
        "n_sessions": len(es), "aggregate": aggregate(rows),
        "limitations": [
            "Walk-forward over daily bars: no intraday touch scoring.",
            "Single instrument (ES) and a single conditioning scheme.",
            "Paired CI assumes independent session errors; overlapping regimes inflate optimism.",
        ],
        "rows": rows,
    }
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    md = render(payload)
    (out / f"MARKET_BRIEF_WALKFORWARD_{stamp}.md").write_text(md, encoding="utf-8")
    (out / "MARKET_BRIEF_WALKFORWARD_LATEST.md").write_text(md, encoding="utf-8")
    (out / "MARKET_BRIEF_WALKFORWARD_LATEST.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    if not a.quiet:
        s = payload["aggregate"]["all"]
        print(json.dumps({
            "n": s["n"], "mean_brier_model": s["mean_brier_model"],
            "mean_brier_base": s["mean_brier_base"],
            "paired_diff": s["paired_mean_diff_base_minus_model"],
            "paired_ci95": s["paired_ci95"], "t": s["paired_t"],
            "beats_base": s["model_beats_base"],
            "hit_rate": s["top_pick_hit_rate"],
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())