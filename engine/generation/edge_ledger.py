"""Edge ledger -- structured, append-only history of every gate v2 verdict.

Mines engine/data/gate_v2_verdicts/{,archive/}*.json into one normalized row per
verdict run, keyed by (symbol, base_family, conditioning, rank, created_at, file)
so re-runs append new rows and re-mining is idempotent. This is the memory the
proposal ranker reads to bias the next experiment toward where edges live.

Standalone stdlib; run with the engine venv python. Read-only on verdicts.

    JARVIS_DATA_ROOT=engine/data .venv/Scripts/python -m engine.generation.edge_ledger
    # or as a plain script:
    .venv/Scripts/python engine/generation/edge_ledger.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DATA_ROOT = Path(
    os.environ.get("JARVIS_DATA_ROOT", str(Path(__file__).resolve().parents[1] / "data"))
)
VERDICT_ROOT = DATA_ROOT / "gate_v2_verdicts"
LEDGER_PATH = DATA_ROOT / "edge_ledger.jsonl"

# Gate v2 thresholds (mirror the verdict files' `thresholds` block). The ALT path
# is the looser of the two gate paths and is the achievable bar for these families.
THRESH = {
    "pf_ci_lower": 1.10,
    "p_edge": 0.95,
    "mc_dd_core_pct": 5.0,
    "mc_dd_alt_pct": 4.0,
    "dsr_core": 0.10,
    "dsr_alt": 0.30,
    "fixed_pf_alt": 1.20,
}
COST_ORDER = ["none", "optimistic", "realistic", "pessimistic", "catastrophic"]
COST_MIN_IDX = COST_ORDER.index("realistic")
WFO_OK = {"MODERATE", "STRONG"}

# Irregular conditioning names that don't follow the "<base>_<seg>_filter" contract.
# (vix verdicts are named "*_vix", not "*_vix_filter".)
_CONDITIONING_SUFFIX = {
    "vix": "vix_filter",
}
# Naming contract: a conditioned family is "<base>_<seg>_filter" (single) or
# "<base>_<seg1>_<seg2>_filter" (stacked), where each <seg> is a registered conditioner
# segment below. The peeler strips known segments right-to-left, so:
#   trend_adx_filter      -> (trend, "adx_filter")
#   trend_adx_rv_filter   -> (trend, "adx_filter+rv_filter")   # canonical sorted "+"-join
#   trend_session_filter  -> (trend, "session_filter")
# Register a segment here to make it stackable; an UNREGISTERED single conditioner still
# parses generically as (base, "<seg>_filter") so a new single seed never silos.
_COND_SEGMENTS = {"adx", "rv", "session", "termstruct"}


def normalize_family(fam: str | None) -> tuple[str, str]:
    """Return (base_family, conditioning). Conditioning is a single token, or a canonical
    sorted "+"-join for stacked conditioners (e.g. "adx_filter+rv_filter"). meanrev is
    canonicalized to mean_reversion."""
    fam = (fam or "?").strip()
    cond = "none"
    base = fam
    for suffix, cond_name in _CONDITIONING_SUFFIX.items():
        token = "_" + suffix
        if fam.endswith(token):
            cond = cond_name
            base = fam[: -len(token)]
            break
    else:
        # "<base>_<seg>..._filter": peel registered conditioner segments right-to-left.
        if fam.endswith("_filter"):
            parts = fam[: -len("_filter")].split("_")
            conds = []
            while len(parts) > 1 and parts[-1] in _COND_SEGMENTS:
                conds.append(parts.pop() + "_filter")
            if conds:
                base, cond = "_".join(parts), "+".join(sorted(conds))
            elif len(parts) > 1:
                # Unregistered single conditioner: "<base>_<seg>_filter" by convention.
                base, cond = "_".join(parts[:-1]), parts[-1] + "_filter"
    if base in ("meanrev", "mean_reversion"):
        base = "mean_reversion"
    return base, cond


def _num(x: Any) -> float | None:
    """Coerce to a finite float, or None. Treats Infinity/NaN as None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    if f != f or f in (float("inf"), float("-inf")):  # NaN or +/-inf
        return None
    return f


def alt_path_failures(m: dict[str, Any]) -> list[str]:
    """Which ALT-path criteria a verdict misses, given its metrics. Empty => alt passes."""
    fails: list[str] = []
    pf = _num(m.get("pf_ci_lower"))
    dsr = _num(m.get("dsr"))
    fixed_pf = _num(m.get("fixed_params_min_pf"))
    mc_dd = _num(m.get("mc_95th_dd_pct"))
    wfo = m.get("wfo_consistency")
    cost = m.get("cost_survives_through")

    # ALT path: pf_ci>=1.1, dsr>=0.3, wfo in {MOD,STRONG}, fixed_pf>=1.2,
    #           cost>=realistic, mc_dd<=4%.
    if pf is None or pf < THRESH["pf_ci_lower"]:
        fails.append("pf_ci<1.10")
    if dsr is None or dsr < THRESH["dsr_alt"]:
        fails.append("dsr<0.30")
    if wfo not in WFO_OK:
        fails.append("wfo_weak")
    if fixed_pf is None or fixed_pf < THRESH["fixed_pf_alt"]:
        fails.append("fixed_pf<1.20")
    if cost not in COST_ORDER or COST_ORDER.index(cost) < COST_MIN_IDX:
        fails.append("cost_death")
    if mc_dd is None or mc_dd > THRESH["mc_dd_alt_pct"]:
        fails.append("mc_dd>4%")
    return fails


# Order in which to attribute the single "primary" block of a FAIL, by how often
# each criterion is fatal across the corpus (graveyard scan 2026-05-30).
_BLOCK_PRIORITY = ["wfo_weak", "cost_death", "dsr<0.30", "fixed_pf<1.20", "pf_ci<1.10", "mc_dd>4%"]


def primary_block(fails: list[str]) -> str | None:
    for c in _BLOCK_PRIORITY:
        if c in fails:
            return c
    return fails[0] if fails else None


def row_from_verdict(path: Path, is_archived: bool) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text())
    except Exception as e:  # corrupt / partial file -- record nothing, surface upstream
        print(f"[skip] {path.name}: {e}")
        return None

    m = d.get("gate_v2_metrics", {}) or {}
    wf = d.get("wfo_config", {}) or {}
    g = d.get("gate_v2", {}) or {}
    base, cond = normalize_family(d.get("family"))
    verdict = d.get("verdict", "?")

    fails = alt_path_failures(m) if verdict == "FAIL" else []
    return {
        "source_file": path.name,
        "is_archived": is_archived,
        "symbol": d.get("symbol", "?"),
        "base_family": base,
        "conditioning": cond,
        "family_raw": d.get("family", "?"),
        "rank": d.get("rank", d.get("hypothesis", "?")),
        "verdict": verdict,
        "passed_via": d.get("passed_via"),
        "core_verdict": d.get("core_verdict"),
        "alt_verdict": d.get("alt_verdict"),
        "created_at": d.get("created_at"),
        "champion_params": d.get("champion_params", {}),
        "design": {
            "train_months": wf.get("train_months"),
            "test_months": wf.get("test_months"),
            "step_months": wf.get("step_months"),
            "n_oos_windows": wf.get("n_oos_windows"),
            "grid_combos": wf.get("grid_combos"),
            "total_oos_trades": wf.get("total_oos_trades") or g.get("total_oos_trades"),
        },
        "metrics": {
            "pf_ci_lower": _num(m.get("pf_ci_lower")),
            "p_edge": _num(m.get("p_edge")),
            "mc_95th_dd_pct": _num(m.get("mc_95th_dd_pct")),
            "dsr": _num(m.get("dsr")),
            "wfo_consistency": m.get("wfo_consistency"),
            "fixed_params_min_pf": _num(m.get("fixed_params_min_pf")),
            "cost_survives_through": m.get("cost_survives_through"),
        },
        "alt_failures": fails,
        "primary_block": primary_block(fails),
    }


def _key(r: dict[str, Any]) -> str:
    return "|".join(
        str(r.get(k))
        for k in ("symbol", "base_family", "conditioning", "rank", "created_at", "source_file")
    )


def load_existing_keys() -> set[str]:
    if not LEDGER_PATH.exists():
        return set()
    keys = set()
    for line in LEDGER_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            keys.add(_key(json.loads(line)))
        except Exception:
            continue
    return keys


def build() -> tuple[int, int]:
    """Mine all verdicts; append only rows not already in the ledger. Returns (new, total)."""
    files = sorted(VERDICT_ROOT.glob("*.json")) + sorted((VERDICT_ROOT / "archive").glob("*.json"))
    existing = load_existing_keys()
    new_rows: list[dict[str, Any]] = []
    for f in files:
        is_archived = f.parent.name == "archive"
        r = row_from_verdict(f, is_archived)
        if r is None:
            continue
        if _key(r) in existing:
            continue
        existing.add(_key(r))
        new_rows.append(r)

    if new_rows:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as fh:
            for r in new_rows:
                fh.write(json.dumps(r) + "\n")
    return len(new_rows), len(existing)


def load_rows() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    rows = []
    for line in LEDGER_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def ranked_ledger() -> list[dict[str, Any]]:
    """Return all ledger rows ranked by edge quality (PASS first, then by dsr desc).

    PASS rows are sorted by dsr descending (best edge first), then by pf_ci_lower
    descending as a tiebreaker.  FAIL rows follow, sorted by primary_block then
    pf_ci_lower descending (nearest-to-pass first -- most promising re-run targets).
    Rows with missing metrics (INSUFFICIENT_SAMPLE) sort last within their group.
    """
    rows = load_rows()

    def _sort_key(r: dict[str, Any]) -> tuple:
        v = r.get("verdict", "?")
        m = r.get("metrics", {})
        dsr = _num(m.get("dsr")) if m else None
        pf = _num(m.get("pf_ci_lower")) if m else None
        # verdict group: PASS=0, INSUFFICIENT_SAMPLE=1, FAIL=2, other=3
        vgroup = {"PASS": 0, "INSUFFICIENT_SAMPLE": 1, "FAIL": 2}.get(v, 3)
        # within group sort: descending dsr/pf (negate for ascending sort)
        dsr_sort = -(dsr if dsr is not None else -999.0)
        pf_sort = -(pf if pf is not None else -999.0)
        return (vgroup, dsr_sort, pf_sort)

    return sorted(rows, key=_sort_key)


if __name__ == "__main__":
    n_new, n_total = build()
    print(f"edge_ledger: +{n_new} new rows, {n_total} total -> {LEDGER_PATH}")
    rows = load_rows()
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    print(f"  {n_pass} PASS / {n_fail} FAIL / {len(rows) - n_pass - n_fail} other")
