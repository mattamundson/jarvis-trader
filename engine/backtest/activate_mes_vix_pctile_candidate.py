"""Activate the frozen MES VIX-percentile candidate from a local gate-v2 verdict.

Reads the verdict JSON produced by ``run_mes_trend_vix_pctile_rank1.py`` and, IFF
it is a genuine gate-v2 PASS whose champion blocked-tier set still matches the
a-priori frozen params, populates ``lock_in_sample`` and flips the candidate from
``paused`` to ``forward_testing``. ``deployed_live`` is never touched (stays False).

Discipline guards (each aborts WITHOUT mutating the registry):
  1. verdict != PASS                      -> nothing to activate; the draft stays paused.
  2. champion_blocked_tiers != frozen set -> the validated strategy is NOT the one we
     froze; per the in-entry activation_protocol, register a NEW id rather than
     mutating these frozen params. This script refuses to do that silently.
  3. resulting registry fails verify_registry -> never write a malformed lock file.

Default is DRY-RUN (prints the proposed entry). Pass --apply to write.

Run locally where the verdict file exists (engine cache + yfinance):

    python engine/backtest/run_mes_trend_vix_pctile_rank1.py      # produces the verdict
    python engine/backtest/activate_mes_vix_pctile_candidate.py   # dry-run, review
    python engine/backtest/activate_mes_vix_pctile_candidate.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import candidate_registry as cr

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_ROOT = os.path.dirname(_HERE)

CANDIDATE_ID = "MES_sma_trend_vix_pctile_blockCrisis_v1"
DEFAULT_VERDICT = os.path.join(
    _ENGINE_ROOT, "data", "gate_v2_verdicts", "MES_trend_vix_pctile_rank1.json"
)


def _build_lock_in_sample(verdict: dict[str, Any]) -> dict[str, Any]:
    """Map the runner's verdict_doc onto the registry's lock_in_sample shape."""
    gate = verdict.get("gate_v2_metrics", {})
    wfo = verdict.get("wfo_config", {})
    return {
        "gate_verdict": verdict.get("verdict"),
        "passed_via": verdict.get("passed_via"),
        "pf_ci_lower": gate.get("pf_ci_lower"),
        "p_edge": gate.get("p_edge"),
        "dsr": gate.get("dsr"),
        "mc_95th_dd": gate.get("mc_95th_dd"),
        "n_oos_windows": wfo.get("n_oos_windows"),
        "total_oos_trades": wfo.get("total_oos_trades"),
        "champion_blocked_tiers": list(verdict.get("champion_blocked_tiers") or []),
        "source_verdict": "engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json",
        "created_at": verdict.get("created_at"),
        "note": (
            "Populated by activate_mes_vix_pctile_candidate.py from the local gate-v2 "
            "verdict. Baseline to beat: MES_trend_vix_rank1 p_edge=0.75 (ALT PASS). "
            "This runner's gate does not emit p_binom; absence is expected."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verdict", default=DEFAULT_VERDICT, help="path to the gate-v2 verdict JSON")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry-run)")
    args = ap.parse_args()

    if not os.path.exists(args.verdict):
        print(f"[ABORT] verdict not found: {args.verdict}")
        print("        Run engine/backtest/run_mes_trend_vix_pctile_rank1.py first.")
        return 2

    with open(args.verdict, encoding="utf-8") as fh:
        verdict = json.load(fh)

    # --- Guard 1: only a genuine PASS may activate ---------------------------
    final = verdict.get("verdict")
    if final != "PASS":
        print(f"[ABORT] verdict is {final!r}, not PASS. Candidate stays 'paused'.")
        print("        A non-PASS run is a result, not a failure to act on.")
        return 1

    # --- Load registry + locate the frozen candidate -------------------------
    registry = cr.load_registry()  # validates on load; raises if malformed
    cand = cr.get_candidate(CANDIDATE_ID, registry)
    if cand is None:
        print(f"[ABORT] candidate {CANDIDATE_ID!r} not in registry.")
        return 2

    if cand.get("status") == "forward_testing":
        print(f"[NOOP] {CANDIDATE_ID} is already 'forward_testing'. Nothing to do.")
        return 0

    # --- Guard 2: validated strategy must be the one we froze ----------------
    frozen_block = sorted(cand.get("params", {}).get("vix_regime_block") or [])
    champion_block = sorted(verdict.get("champion_blocked_tiers") or [])
    if champion_block != frozen_block:
        print("[ABORT] champion blocked-tier set does not match the frozen params.")
        print(f"          frozen   vix_regime_block = {frozen_block}")
        print(f"          champion blocked_tiers    = {champion_block}")
        print("        Per the activation_protocol, register a NEW id with the champion's")
        print("        params rather than mutating these frozen ones. Not done automatically.")
        return 1

    # --- Apply in-memory, then re-validate before writing --------------------
    cand["status"] = "forward_testing"
    cand["deployed_live"] = False  # invariant: activation never deploys live
    cand["lock_in_sample"] = _build_lock_in_sample(verdict)

    problems = cr.verify_registry(registry)
    if problems:
        print("[ABORT] resulting registry would be invalid:")
        for p in problems:
            print(f"          - {p}")
        return 2

    print(f"=== Proposed activation of {CANDIDATE_ID} ===")
    print(json.dumps(cand, indent=2))
    print("=" * 60)

    if not args.apply:
        print("[DRY-RUN] no file written. Re-run with --apply to commit the change.")
        return 0

    with open(cr._DEFAULT_REGISTRY, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2)
        fh.write("\n")

    # --- Confirm post-write invariants ---------------------------------------
    fresh = cr.load_registry()
    active_ids = {c["id"] for c in cr.get_active_candidates(fresh)}
    live_mes = cr.live_candidate_for_symbol("MES", fresh)
    print(f"[APPLIED] {CANDIDATE_ID} -> forward_testing")
    print(f"          now in get_active_candidates : {CANDIDATE_ID in active_ids}")
    print(f"          live_candidate_for_symbol(MES): {live_mes}  (must stay None)")
    if live_mes is not None:
        print("[WARN] a candidate is now deployed_live for MES — verify this was intended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
