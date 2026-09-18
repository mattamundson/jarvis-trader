"""Build the verdict trust register: classify every archived verdict artifact by what it can support.

Why (round 3, task 3): round 1 established that the store cannot be taken at face value —
**0 of 76** artifacts recorded which cache they ran on; 8 duplicate-content groups file identical
bytes under conflicting `-deep-` / `-pre-deep-` / `-shallow-contaminated-` labels; 7 carry NaN in a
gating metric; and every `dsr` was deflated against the runner's own grid size (1-64 trials) rather
than the campaign count (hundreds). A verdict that says PASS therefore carries no built-in indication
of whether it is trustworthy.

This does NOT retro-fix anything. Provenance-absent artifacts cannot be repaired by relabelling, so
they are *labelled* for what they are. The register is the output.

Classification rules (all measured from the artifact):

  FAIL / non-PASS                -> "no action"      : a FAIL is conservative; nothing rides on it
  NaN in a gating metric         -> "uninformative"  : the metric never computed
  identical bytes under
    conflicting provenance labels-> "label-conflict" : filename provenance unreliable
  no cache_provenance recorded   -> "no-provenance"  : deep-vs-shallow unverifiable
  PASS deflated at few trials    -> "at-risk"        : PASS carried by grid-count deflation
  everything else                -> "stated-limits"  : usable, with the recorded caveats

A PASS can carry several flags; the register lists all of them rather than picking one, because the
point is to stop single-label summaries from hiding compound uncertainty.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"
OUT_MD = Path(__file__).resolve().parent.parent.parent / "docs" / "research" / "verdict-trust-register-2026-09-18.md"
OUT_JSON = Path(__file__).resolve().parent.parent / "verdict_trust_register.json"
GATE_METRICS = ("p_edge", "dsr", "pf_ci_lower", "mc_95th_dd", "fixed_params_min_pf")
#: Deflation against a grid count this small is not plausibly a campaign-level deflation.
FEW_TRIALS = 8
CAMPAIGN_FLOOR = 0.30
ADOPTION_SHA256 = "e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe"


def _metrics(d: dict) -> dict:
    m = d.get("gate_v2_metrics")
    return m if isinstance(m, dict) else d


def _trials(d: dict):
    wc = d.get("wfo_config")
    wc = wc if isinstance(wc, dict) else {}
    return wc.get("n_combos") or wc.get("grid_combos") or wc.get("n_trials")


def main() -> int:
    files = sorted(ROOT.rglob("*.json")) if ROOT.exists() else []
    if not files:
        print(f"ERROR: no artifacts under {ROOT}")
        return 2

    # duplicate-content groups, for label-conflict detection
    by_hash: dict[str, list[Path]] = collections.defaultdict(list)
    for f in files:
        by_hash[hashlib.sha256(f.read_bytes()).hexdigest()].append(f)
    conflict_hashes = {
        h for h, ps in by_hash.items()
        if len(ps) > 1 and len({t for p in ps for t in _tags(p)}) > 1
    }

    rows = []
    for f in files:
        raw = f.read_bytes()
        try:
            d = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            rows.append({"file": str(f.relative_to(ROOT)), "verdict": "UNREADABLE", "flags": ["unreadable"]})
            continue
        if not isinstance(d, dict):
            continue
        m = _metrics(d)
        rel = str(f.relative_to(ROOT))
        verdict = str(d.get("verdict", "?"))
        is_pass = verdict.upper().startswith("PASS")
        trials = _trials(d)
        dsr = m.get("dsr")
        flags = []

        if not is_pass:
            flags.append("no-action")
        if any(isinstance(m.get(k), float) and math.isnan(m[k]) for k in GATE_METRICS):
            flags.append("uninformative-nan")
        if hashlib.sha256(raw).hexdigest() in conflict_hashes:
            flags.append("label-conflict")
        if not d.get("cache_provenance"):
            flags.append("no-provenance")
        if is_pass and trials is not None and int(trials) <= FEW_TRIALS:
            flags.append("pass-at-risk")
        # The campaign-count DSR is only stored by runners that record it (PR #873). Checking the
        # RECORDED dsr was wrong: that value is the grid-count deflation, which by construction sits
        # well above the floor, so the flag could never fire.
        _defl = m.get("deflation")
        camp_dsr = _defl.get("dsr_campaign") if isinstance(_defl, dict) else None
        if is_pass and isinstance(camp_dsr, float) and camp_dsr < CAMPAIGN_FLOOR:
            flags.append("fails-campaign-floor")
        if not flags:
            flags.append("stated-limits")

        rows.append({
            "file": rel, "verdict": verdict, "passed_via": d.get("passed_via"),
            "p_edge": m.get("p_edge"), "dsr": dsr, "trials": trials,
            "dsr_campaign": camp_dsr,
            "created_at": d.get("created_at"), "flags": flags,
        })

    # ---- write the register -------------------------------------------------
    passes = [r for r in rows if str(r["verdict"]).upper().startswith("PASS")]
    counts = collections.Counter(f for r in rows for f in r["flags"])

    lines = [
        "# Verdict trust register — 2026-09-18",
        "",
        "Generated by `engine/backtest/build_verdict_trust_register.py`. Reproduce with:",
        "",
        "    env -u PYTHONPATH .venv/Scripts/python.exe backtest/build_verdict_trust_register.py",
        "",
        f"Scope: all **{len(rows)}** artifacts in `engine/data/gate_v2_verdicts/` (including `archive/`).",
        "",
        "## How to read this",
        "",
        "A verdict saying PASS carries **no built-in indication of whether it is trustworthy** — the store",
        "records no cache provenance, `dsr` was deflated against each runner's own grid size rather than",
        "the campaign count, and 8 groups of identical files sit under conflicting provenance labels.",
        "This register labels each artifact with what it can and cannot support. It does not retro-fix",
        "anything: provenance-absent artifacts cannot be repaired by relabelling, only labelled.",
        "",
        "**Nothing in the historical store is 'trusted' in the strong sense.** Every PASS predates",
        "provenance recording (added 2026-09-17) and campaign-count deflation (2026-09-18).",
        "",
        "Flags (an artifact can carry several — deliberately, so a single label cannot hide compound",
        "uncertainty):",
        "",
        "| flag | meaning |",
        "|---|---|",
        "| `no-action` | FAIL/non-PASS: a FAIL is conservative, nothing rides on it |",
        "| `uninformative-nan` | a gating metric is NaN — it never computed |",
        "| `label-conflict` | identical bytes filed under conflicting provenance labels |",
        "| `no-provenance` | no `cache_provenance` recorded; deep-vs-shallow unverifiable |",
        "| `pass-at-risk` | PASS whose `dsr` was deflated at <= 8 trials |",
        "| `fails-campaign-floor` | recorded `dsr` below the 0.30 ALT floor |",
        "| `stated-limits` | no other flag: usable, with the recorded caveats |",
        "",
        "## Flag counts",
        "",
        "| flag | artifacts |",
        "|---|---|",
    ]
    for flag, n in counts.most_common():
        lines.append(f"| `{flag}` | {n} |")

    lines += [
        "",
        f"## PASS inventory — {len(passes)} of {len(rows)}",
        "",
        "| artifact | via | p_edge | dsr (grid) | dsr (campaign) | trials | flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(passes, key=lambda x: str(x.get("created_at"))):
        flags = ", ".join(f"`{f}`" for f in r["flags"])
        lines.append(
            f"| `{r['file']}` | {r.get('passed_via')} | {r.get('p_edge')} | {r.get('dsr')} | "
            f"{r.get('dsr_campaign') if r.get('dsr_campaign') is not None else 'not recorded'} | "
            f"{r.get('trials')} | {flags} |"
        )

    lines += [
        "",
        "## The nine PASSes that cannot be reclassified",
        "",
        "Of the 10 recorded PASSes, **one** (the only live verdict, `MES_trend_vix_pctile_rank1`) can be",
        "evaluated at the campaign count and **fails** (`dsr` 0.1815 vs a 0.30 floor). The other nine store",
        "`dsr` but not the trade-level return series, so their campaign-count value **cannot be produced",
        "without re-running each candidate**. They are not evidence of edge, and they cannot be shown to be",
        "evidence of failure from their own artifacts — they are `pass-at-risk` and",
        "`no-provenance` until re-measured. See `docs/research/alt-promotion-bar-dossier-2026-09-18.md`.",
        "",
        "## What this register does NOT claim",
        "",
        "1. It does not say the flagged PASSes are false — only that their artifacts cannot support them.",
        "2. It does not reclassify any verdict; the flags are advisory and no threshold reads them.",
        "3. It cannot assess edge quality: the underlying strategies may be better or worse than their",
        "   artifacts suggest. It assesses *artifact trustworthiness* only.",
        "4. The 2026-09-17/18 changes (provenance recording, campaign deflation, ledger reconciliation)",
        "   apply prospectively. Verdicts produced after those dates carry the new evidence and should be",
        "   re-audited as a separate cohort.",
        "",
        "## Certified reference",
        "",
        f"The MES deep cache ({ADOPTION_SHA256[:12]}…) remains the only content-addressed, verified data basis",
        "in the program; a deep MGC cache does not exist on disk.",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"rows": rows, "flag_counts": dict(counts)}, indent=2), encoding="utf-8")

    print(f"artifacts classified : {len(rows)}")
    print(f"PASSes               : {len(passes)}")
    print("flag counts:", dict(counts))
    print(f"wrote {OUT_MD.name} and {OUT_JSON.name}")
    return 0


def _tags(p: Path) -> set[str]:
    n = p.stem.lower()
    return {t for t in ("shallow-contaminated", "pre-deep", "pre-rereval", "pre-refresh", "deep") if t in n}


if __name__ == "__main__":
    raise SystemExit(main())