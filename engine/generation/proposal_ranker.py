"""Proposal ranker -- the generator's first artifact.

Reads engine/data/edge_ledger.jsonl (the validator's memory) and ranks the next
experiments to run by an empirical prior over the (base_family x instrument x
conditioning) space. Biases toward where edges have actually survived gate v2 and
away from the graveyard. Emits three tiers:

  A. ENABLE   -- already PASSed gate v2, not yet in paper. Zero new compute.
  B. NOVEL    -- untested cell with a non-trivial prior; runnable on existing bars.
  C. DEAD     -- already FAILed and/or zero family-wide passes; do NOT re-run.

The ranker scores only within the conditioning vocabulary it has *observed*
(none, rv_filter, vix_filter). Inventing a new conditioner type (ADX, session,
term-structure) is a human decision -- the ranker flags that boundary rather than
fabricating a prior for something it has no evidence on.

    .venv/Scripts/python engine/generation/proposal_ranker.py
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge_ledger import COST_ORDER, WFO_OK, load_rows  # type: ignore

DATA_ROOT = Path(
    os.environ.get("JARVIS_DATA_ROOT", str(Path(__file__).resolve().parents[1] / "data"))
)
OUT_PATH = DATA_ROOT / "next_experiments.json"

# Prior weights. Family carries the most signal (only trend has ever passed),
# instrument next (only MES/MGC), conditioning last but decisive between variants.
W_FAMILY, W_INSTRUMENT, W_CONDITIONING = 0.45, 0.35, 0.20
PRIOR_RATE, PRIOR_STRENGTH = 0.15, 2.0  # Beta(prior*strength, (1-prior)*strength)
NOVELTY_BONUS = 1.25  # untested cell: information value
RETREAD_PENALTY = 0.35  # this exact design already FAILed: low value to repeat
TOP_NOVEL = 8


def smoothed_rate(n_pass: int, n_tested: int) -> float:
    """Beta-binomial posterior mean. 0/7 -> low but non-zero; 2/2 -> high but < 1."""
    a = PRIOR_RATE * PRIOR_STRENGTH
    b = (1 - PRIOR_RATE) * PRIOR_STRENGTH
    return (n_pass + a) / (n_tested + a + b)


def _scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [r for r in rows if r["verdict"] in ("PASS", "FAIL")]

    # marginal pass rates
    fam_t, fam_p = Counter(), Counter()
    inst_t, inst_p = Counter(), Counter()
    cond_t, cond_p = Counter(), Counter()
    # per-cell aggregation
    cell: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"tested": 0, "passed": 0, "blocks": Counter(), "best_pf": None, "best_dsr": None}
    )
    instruments_with_data: set[str] = set()

    for r in rows:
        base, sym, cond = r["base_family"], r["symbol"], r["conditioning"]
        is_pass = r["verdict"] == "PASS"
        fam_t[base] += 1
        inst_t[sym] += 1
        cond_t[cond] += 1
        if is_pass:
            fam_p[base] += 1
            inst_p[sym] += 1
            cond_p[cond] += 1
        c = cell[(base, sym, cond)]
        c["tested"] += 1
        c["passed"] += int(is_pass)
        if r.get("primary_block"):
            c["blocks"][r["primary_block"]] += 1
        pf = r["metrics"].get("pf_ci_lower")
        if pf is not None and (c["best_pf"] is None or pf > c["best_pf"]):
            c["best_pf"] = pf
        instruments_with_data.add(sym)  # a verdict exists => bars existed to run it

    fam_rate = {k: smoothed_rate(fam_p[k], fam_t[k]) for k in fam_t}
    inst_rate = {k: smoothed_rate(inst_p[k], inst_t[k]) for k in inst_t}
    cond_rate = {k: smoothed_rate(cond_p[k], cond_t[k]) for k in cond_t}

    bases = sorted(fam_t)
    syms = sorted(inst_t)
    conds = sorted(cond_t)

    candidates: list[dict[str, Any]] = []
    for base in bases:
        for sym in syms:
            for cond in conds:
                c = cell.get((base, sym, cond))
                tested = c["tested"] if c else 0
                passed = c["passed"] if c else 0
                base_score = (
                    W_FAMILY * fam_rate[base]
                    + W_INSTRUMENT * inst_rate[sym]
                    + W_CONDITIONING * cond_rate[cond]
                )
                if tested == 0:
                    mult, status = NOVELTY_BONUS, "untested"
                elif passed > 0:
                    mult, status = 0.0, "already_passed"  # handled in ENABLE tier, not re-proposed
                else:
                    mult, status = RETREAD_PENALTY, "failed"
                score = base_score * mult
                # honest hard-floor: a base family with zero passes anywhere is a dead family
                family_dead = fam_p[base] == 0
                candidates.append(
                    {
                        "base_family": base,
                        "instrument": sym,
                        "conditioning": cond,
                        "status": status,
                        "tested": tested,
                        "passed": passed,
                        "family_pass_rate": round(fam_rate[base], 3),
                        "instrument_pass_rate": round(inst_rate[sym], 3),
                        "conditioning_pass_rate": round(cond_rate[cond], 3),
                        "score": round(score, 4),
                        "family_dead": family_dead,
                        "runnable_now": sym in instruments_with_data,
                        "primary_blocks": dict(c["blocks"]) if c else {},
                    }
                )
    return candidates


def _enable_tier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Already-PASSed configs -- the edge you already own. Enablement is a Tier-3 call."""
    out = []
    for r in rows:
        if r["verdict"] != "PASS":
            continue
        out.append(
            {
                "instrument": r["symbol"],
                "family": r["family_raw"],
                "rank": r["rank"],
                "passed_via": r["passed_via"],
                "champion_params": r["champion_params"],
                "pf_ci_lower": r["metrics"].get("pf_ci_lower"),
                "dsr": r["metrics"].get("dsr"),
                "wfo": r["metrics"].get("wfo_consistency"),
                "mc_dd_pct": r["metrics"].get("mc_95th_dd_pct"),
                "cost_survives_through": r["metrics"].get("cost_survives_through"),
                "total_oos_trades": r["design"].get("total_oos_trades"),
                "source_file": r["source_file"],
                "is_archived": r["is_archived"],
            }
        )
    # de-dup identical champion configs (re-runs); keep the most robust by cost then pf
    seen: dict[tuple, dict] = {}
    for o in out:
        k = (o["instrument"], o["family"], json.dumps(o["champion_params"], sort_keys=True))
        cur = seen.get(k)
        if cur is None:
            seen[k] = o
            continue
        better_cost = COST_ORDER.index(o["cost_survives_through"] or "none") > COST_ORDER.index(
            cur["cost_survives_through"] or "none"
        )
        if better_cost:
            seen[k] = o
    return sorted(seen.values(), key=lambda o: (o["instrument"], o["family"]))


def rank() -> dict[str, Any]:
    rows = load_rows()
    cands = _scored(rows)

    enable = _enable_tier(rows)
    # NOVEL: untested, not in a dead family, runnable now -- ranked by prior.
    novel = [
        c for c in cands if c["status"] == "untested" and not c["family_dead"] and c["runnable_now"]
    ]
    novel.sort(key=lambda c: c["score"], reverse=True)
    # DEAD: already failed, or any candidate in a family that never passed.
    dead = [c for c in cands if c["status"] == "failed" or c["family_dead"]]
    dead.sort(key=lambda c: (c["base_family"], c["instrument"], c["conditioning"]))

    return {
        "generated_from": "edge_ledger.jsonl",
        "n_verdicts": len(rows),
        "weights": {"family": W_FAMILY, "instrument": W_INSTRUMENT, "conditioning": W_CONDITIONING},
        "tier_A_enable": enable,
        "tier_B_novel_runnable": novel[:TOP_NOVEL],
        "tier_C_dead_do_not_run": dead,
        "vocabulary_note": (
            "Ranker scores only observed conditioners (none, rv_filter, vix_filter). "
            "New conditioner types (ADX/trend-strength, session-time, gold term-structure) "
            "have no prior in the corpus and require a human seed before they can be ranked."
        ),
    }


def _fmt_novel(c: dict[str, Any]) -> str:
    cond = c["conditioning"]
    return (
        f"  {c['base_family']:14} x {c['instrument']:4} x {cond:10} "
        f"score={c['score']:.3f}  (fam={c['family_pass_rate']} "
        f"inst={c['instrument_pass_rate']} cond={c['conditioning_pass_rate']})"
    )


if __name__ == "__main__":
    result = rank()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))

    print(f"\n=== TIER A: ENABLE (already passed gate v2, verify-then-enable) ===")
    for e in result["tier_A_enable"]:
        flag = " [archived run]" if e["is_archived"] else ""
        print(
            f"  {e['instrument']}/{e['family']} via {e['passed_via']}: "
            f"pf_ci={e['pf_ci_lower']} dsr={e['dsr']} wfo={e['wfo']} "
            f"mc_dd={e['mc_dd_pct']}% cost<= {e['cost_survives_through']} "
            f"trades={e['total_oos_trades']}{flag}"
        )

    print(f"\n=== TIER B: NOVEL experiments, runnable on existing bars (top {TOP_NOVEL}) ===")
    for c in result["tier_B_novel_runnable"]:
        print(_fmt_novel(c))

    print(
        f"\n=== TIER C: DEAD -- do NOT re-run ({len(result['tier_C_dead_do_not_run'])} cells) ==="
    )
    dead_fams = Counter(c["base_family"] for c in result["tier_C_dead_do_not_run"])
    for fam, n in dead_fams.most_common():
        print(f"  {fam:16} {n} dead cells")

    print(f"\n{result['vocabulary_note']}")
    print(f"\nwrote -> {OUT_PATH}")
