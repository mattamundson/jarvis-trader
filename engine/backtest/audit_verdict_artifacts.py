"""Audit the verdict artifact store: provenance, duplicates, NaN gates, trial counts.

Created 2026-09-17 after the cost-ledger and p_edge corrections showed that the program's
problem is not "find more strategies" but "the recorded evidence cannot be trusted at a
glance". This makes the store auditable in one command instead of by inference.

What it checks (all measured):

1. **Duplicate artifact contents.** Sha256 per file, grouped. A file labelled `*-deep-*` that is
   byte-identical to one labelled `*-shallow-contaminated-*` or `*-pre-deep-*` is a *copied*
   artifact, not a deep re-run — two genuine runs cannot share bytes (they differ at minimum in
   `created_at`). Such a pair cannot support any claim that the deep cache certified the edge.
2. **NaN in a gating metric.** NaN makes `pf_ci_lower >= floor` False, so it fails SAFELY — but
   it means the bootstrap never ran, which is a sample-adequacy signal worth surfacing rather
   than silently reporting as an ordinary failure.
3. **Recorded deflation inputs.** `wfo_config.n_combos` is the runner's *own grid size*, not the
   campaign trial count. Recording it makes the under-deflation visible per verdict.
4. **PASS inventory vs the documented ALT bar.** The ALT conjunction does not gate on `p_edge`,
   so a verdict can read "PASS via alt" below the documented 0.60 activation bar.

Run from `engine/`:
    env -u PYTHONPATH .venv/Scripts/python.exe backtest/audit_verdict_artifacts.py
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
from pathlib import Path

VERDICT_ROOT = Path(__file__).parent.parent / "data" / "gate_v2_verdicts"
GATE_METRICS = ("p_edge", "dsr", "pf_ci_lower", "mc_95th_dd", "fixed_params_min_pf")
#: Documented ALT activation criterion (docs), NOT enforced by the ALT conjunction in code.
DOCUMENTED_ALT_P_EDGE = 0.60


def _metrics(d: dict) -> dict:
    m = d.get("gate_v2_metrics")
    return m if isinstance(m, dict) else d


def _trial_count(d: dict):
    wc = d.get("wfo_config")
    if not isinstance(wc, dict):
        wc = {}
    return wc.get("n_combos") or wc.get("grid_combos") or wc.get("n_trials")


def _label_tag(path: Path) -> set[str]:
    """Provenance tags implied by the filename."""
    n = path.stem.lower()
    tags = set()
    for tag in ("shallow-contaminated", "pre-deep", "pre-rereval", "pre-refresh", "deep"):
        if tag in n:
            tags.add(tag)
    return tags


def main() -> int:
    if not VERDICT_ROOT.exists():
        print(f"ERROR: verdict root not found: {VERDICT_ROOT}")
        return 2

    files = sorted(VERDICT_ROOT.rglob("*.json"))
    print(f"verdict root : {VERDICT_ROOT}")
    print(f"json files   : {len(files)}")

    # ---- 1. duplicate contents -------------------------------------------------
    by_hash: dict[str, list[Path]] = collections.defaultdict(list)
    for f in files:
        by_hash[hashlib.sha256(f.read_bytes()).hexdigest()].append(f)
    dups = {h: ps for h, ps in by_hash.items() if len(ps) > 1}

    print(f"\n=== 1. duplicate artifact contents: {len(dups)} group(s) "
          f"covering {sum(len(p) for p in dups.values())} files ===")
    suspicious = []
    for h, ps in sorted(dups.items(), key=lambda kv: -len(kv[1])):
        labels = {t for p in ps for t in _label_tag(p)}
        rels = [str(p.relative_to(VERDICT_ROOT)) for p in ps]
        flag = ""
        # A deep-labelled artifact sharing bytes with a non-deep provenance label is the
        # defect this audit exists to catch.
        if "deep" in labels and (labels - {"deep"}):
            flag = "  <-- PROVENANCE CONFLICT: identical bytes, different data provenance"
            suspicious.append(rels)
        print(f"  {h[:16]}  ({len(ps)} files) labels={sorted(labels) or ['<none>']}{flag}")
        for r in rels:
            print(f"      {r}")
    if not dups:
        print("  none")
    print(f"\nprovenance conflicts: {len(suspicious)}")

    # ---- 2/3/4 per-file -------------------------------------------------------
    nan_rows, trial_rows, passes = [], [], []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - corrupt artifact is the finding
            print(f"  [UNREADABLE] {f.name}: {exc}")
            continue
        if not isinstance(d, dict):
            continue
        m = _metrics(d)
        rel = str(f.relative_to(VERDICT_ROOT))
        nans = [k for k in GATE_METRICS if isinstance(m.get(k), float) and math.isnan(m[k])]
        if nans:
            nan_rows.append((rel, nans))
        tc = _trial_count(d)
        if tc is not None:
            trial_rows.append((rel, tc))
        if str(d.get("verdict", "")).upper().startswith("PASS"):
            passes.append({
                "file": rel,
                "verdict": d.get("verdict"),
                "passed_via": d.get("passed_via"),
                "p_edge": m.get("p_edge"),
                "dsr": m.get("dsr"),
                "pf_ci_lower": m.get("pf_ci_lower"),
                "wfo_consistency": m.get("wfo_consistency"),
                "fixed_params_min_pf": m.get("fixed_params_min_pf"),
                "trial_count_recorded": tc,
                "created_at": d.get("created_at"),
                "symbol": d.get("symbol"),
                "p_edge_below_documented_alt_bar": (
                    isinstance(m.get("p_edge"), float)
                    and m["p_edge"] < DOCUMENTED_ALT_P_EDGE
                ),
            })

    print(f"\n=== 2. NaN in a gating metric: {len(nan_rows)} file(s) "
          f"(fails SAFELY: NaN >= floor is False) ===")
    for rel, nans in nan_rows:
        print(f"  {rel:58s} {nans}")

    print(f"\n=== 3. recorded deflation input (runner grid, NOT campaign count): "
          f"{len(trial_rows)} of {len(files)} files ===")
    counts = collections.Counter(tc for _, tc in trial_rows)
    print(f"  distinct recorded counts: {dict(sorted(counts.items(), key=lambda kv: str(kv[0])))}")
    print("  NOTE: these are the runner's own grid sizes. The true campaign trial count against the")
    print("        deep cache is in the hundreds, so every recorded DSR is UNDER-deflated.")

    print(f"\n=== 4. PASS inventory: {len(passes)} ===")
    for p in sorted(passes, key=lambda x: str(x["created_at"])):
        mark = "  <-- BELOW documented 0.60 ALT bar" if p["p_edge_below_documented_alt_bar"] else ""
        print(f"  {p['file']:58s} via={p['passed_via']:5s} p_edge={p['p_edge']} dsr={p['dsr']} "
              f"trials={p['trial_count_recorded']}{mark}")

    out = Path("verdict_artifact_audit.json")
    out.write_text(json.dumps({
        "n_files": len(files),
        "duplicate_groups": {h: [str(p.relative_to(VERDICT_ROOT)) for p in ps] for h, ps in dups.items()},
        "provenance_conflicts": suspicious,
        "nan_gate_metrics": [{"file": r, "metrics": n} for r, n in nan_rows],
        "trial_counts_recorded": dict(trial_rows),
        "verdicts_with_recorded_trials": len(trial_rows),
        "passes": passes,
        "documented_alt_p_edge_bar": DOCUMENTED_ALT_P_EDGE,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
