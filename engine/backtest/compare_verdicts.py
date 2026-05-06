#!/usr/bin/env python
"""
Verdict Comparison Tool — Champion-Param Drift Detection

Diffs two gate v2 verdict JSON files (typically OLD vs REFRESHED) and surfaces:
  - Verdict transitions (PASS -> FAIL, FAIL -> PASS, PASS -> PASS-shifted-params)
  - Champion-parameter changes (fast/slow/atr_trail_mult drift)
  - Metric deltas (pf_ci_lower, p_edge, dsr, mc_dd, etc.)
  - OOS sample-size changes (more bars means more confidence)

Designed for the verdict-refresh workflow: when MES rank11 or MGC rank4 are
re-run before their 2026-06-05/06 expiry, this answers "did the champion
hold or did the regime shift?" — the binary decision between committing
the refresh as-is vs. rolling forward to rank12 / rank5.

Usage (from engine/ directory):
    .venv/Scripts/python -m backtest.compare_verdicts <old.json> <new.json>
    .venv/Scripts/python -m backtest.compare_verdicts \\
        engine/data/gate_v2_verdicts/archive/MES_trend_rank11.json \\
        engine/data/gate_v2_verdicts/MES_trend_rank11.json
    .venv/Scripts/python -m backtest.compare_verdicts old.json new.json --json

Exit codes:
    0 — no significant drift; safe to commit refreshed verdict
    1 — verdict transition or significant param drift; manual review needed
    2 — file read or parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Param drift threshold: a champion param is "drifted" if it's > this fraction
# different from the prior champion. 0.10 = 10%.
PARAM_DRIFT_THRESHOLD = 0.10

# Metrics to compare; key = field name in gate_v2_metrics, value = label
METRIC_FIELDS = [
    ("pf_ci_lower", "pf_ci"),
    ("p_edge", "p_edge"),
    ("dsr", "dsr"),
    ("mc_95th_dd_pct", "mc_dd%"),
    ("fixed_params_min_pf", "fixed_min_pf"),
    ("wfo_consistency", "wfo"),
    ("cost_survives_through", "cost"),
]


def _load(path: Path) -> dict[str, Any]:
    """Load a verdict JSON, returning the parsed dict or raising FileNotFoundError/JSONDecodeError."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _safe_get(d: dict, *keys, default=None):
    """Walk nested dict by keys, returning default if any step is missing."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _is_drifted(old: float | int | None, new: float | int | None, threshold: float) -> bool:
    """True if relative change exceeds threshold. Handles None and zero gracefully."""
    if old is None or new is None:
        return False
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return False
    if old == 0:
        return new != 0
    return abs(new - old) / abs(old) > threshold


def compare(old: dict, new: dict) -> dict[str, Any]:
    """Compute a structured diff between two verdicts."""
    # Top-level identity
    summary = {
        "old_file": old.get("__file"),
        "new_file": new.get("__file"),
        "old_symbol": old.get("symbol"),
        "new_symbol": new.get("symbol"),
        "old_family": old.get("family"),
        "new_family": new.get("family"),
        "old_verdict": old.get("verdict"),
        "new_verdict": new.get("verdict"),
        "old_passed_via": old.get("passed_via"),
        "new_passed_via": new.get("passed_via"),
        "verdict_transition": None,
        "champion_drift": [],
        "metric_deltas": {},
        "oos_delta": None,
        "warnings": [],
    }

    # Sanity: same symbol/family
    if summary["old_symbol"] != summary["new_symbol"]:
        summary["warnings"].append(
            f"Symbol mismatch: old={summary['old_symbol']} new={summary['new_symbol']}"
        )
    if summary["old_family"] != summary["new_family"]:
        summary["warnings"].append(
            f"Family mismatch: old={summary['old_family']} new={summary['new_family']}"
        )

    # Verdict transition
    old_v, new_v = summary["old_verdict"], summary["new_verdict"]
    old_via, new_via = summary["old_passed_via"], summary["new_passed_via"]
    if old_v != new_v:
        summary["verdict_transition"] = f"{old_v} -> {new_v}"
    elif old_v == "PASS" and new_v == "PASS" and old_via != new_via:
        summary["verdict_transition"] = f"PASS-{old_via} -> PASS-{new_via}"
    else:
        summary["verdict_transition"] = "no transition"

    # Champion params
    old_champ = old.get("champion_params", {}) or {}
    new_champ = new.get("champion_params", {}) or {}
    all_keys = sorted(set(old_champ.keys()) | set(new_champ.keys()))
    for k in all_keys:
        ov = old_champ.get(k)
        nv = new_champ.get(k)
        if ov == nv:
            continue
        # Compute drift for numeric params
        if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
            drift_pct = abs(nv - ov) / abs(ov) * 100 if ov != 0 else float("inf")
            summary["champion_drift"].append(
                {
                    "param": k,
                    "old": ov,
                    "new": nv,
                    "drift_pct": round(drift_pct, 2),
                    "exceeds_threshold": _is_drifted(ov, nv, PARAM_DRIFT_THRESHOLD),
                }
            )
        else:
            summary["champion_drift"].append(
                {"param": k, "old": ov, "new": nv, "drift_pct": None, "exceeds_threshold": True}
            )

    # Metric deltas
    old_m = _safe_get(old, "gate_v2_metrics", default={}) or {}
    new_m = _safe_get(new, "gate_v2_metrics", default={}) or {}
    for field, label in METRIC_FIELDS:
        ov = old_m.get(field)
        nv = new_m.get(field)
        if ov is None and nv is None:
            continue
        # Numeric delta
        if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
            summary["metric_deltas"][label] = {
                "old": ov,
                "new": nv,
                "delta": round(nv - ov, 4),
            }
        elif ov != nv:
            summary["metric_deltas"][label] = {"old": ov, "new": nv, "delta": "string"}

    # OOS coverage change — proxy for statistical confidence
    old_n = _safe_get(old, "wfo_config", "total_oos_trades", default=0) or 0
    new_n = _safe_get(new, "wfo_config", "total_oos_trades", default=0) or 0
    summary["oos_delta"] = {
        "old_total_oos_trades": old_n,
        "new_total_oos_trades": new_n,
        "delta": new_n - old_n,
    }

    # Decision
    significant_drift = any(d.get("exceeds_threshold") for d in summary["champion_drift"])
    verdict_changed = summary["verdict_transition"] != "no transition"
    summary["needs_review"] = bool(verdict_changed or significant_drift or summary["warnings"])

    return summary


def _print_table(diff: dict[str, Any]) -> None:
    print()
    print("=" * 80)
    print(f"VERDICT COMPARISON: {diff['old_symbol']} {diff['old_family']}")
    print(
        f"  OLD: {diff['old_file'] or '(unnamed)'}  ({diff['old_verdict']}-{diff['old_passed_via']})"
    )
    print(
        f"  NEW: {diff['new_file'] or '(unnamed)'}  ({diff['new_verdict']}-{diff['new_passed_via']})"
    )
    print("=" * 80)

    print(f"\nVerdict transition: {diff['verdict_transition']}")

    # Warnings
    if diff["warnings"]:
        print("\nWARNINGS:")
        for w in diff["warnings"]:
            print(f"  ! {w}")

    # Champion drift
    print("\nChampion params:")
    if not diff["champion_drift"]:
        print("  (no change)")
    else:
        for d in diff["champion_drift"]:
            ov = d["old"]
            nv = d["new"]
            mark = " <-- DRIFT" if d.get("exceeds_threshold") else ""
            pct = f" ({d['drift_pct']:.1f}%)" if d.get("drift_pct") is not None else ""
            print(f"  {d['param']:20s}: {ov} -> {nv}{pct}{mark}")

    # Metrics
    print("\nGate v2 metrics:")
    if not diff["metric_deltas"]:
        print("  (no change)")
    else:
        print(f"  {'metric':20s} {'old':>12s} {'new':>12s} {'delta':>10s}")
        for label, d in diff["metric_deltas"].items():
            ov = d["old"]
            nv = d["new"]
            delta = d["delta"]
            ov_s = f"{ov:.4f}" if isinstance(ov, (int, float)) else str(ov)
            nv_s = f"{nv:.4f}" if isinstance(nv, (int, float)) else str(nv)
            d_s = f"{delta:+.4f}" if isinstance(delta, (int, float)) else str(delta)
            print(f"  {label:20s} {ov_s:>12s} {nv_s:>12s} {d_s:>10s}")

    # OOS coverage
    od = diff["oos_delta"]
    print(
        f"\nOOS sample size: {od['old_total_oos_trades']} -> {od['new_total_oos_trades']} ({od['delta']:+d} trades)"
    )

    # Decision
    print()
    print("=" * 80)
    if diff["needs_review"]:
        print("DECISION: MANUAL REVIEW NEEDED")
        if diff["verdict_transition"] != "no transition":
            print(f"  - Verdict changed: {diff['verdict_transition']}")
        drifted = [d for d in diff["champion_drift"] if d.get("exceeds_threshold")]
        if drifted:
            print(
                f"  - {len(drifted)} champion param(s) drifted >{PARAM_DRIFT_THRESHOLD * 100:.0f}%"
            )
        if diff["warnings"]:
            print(f"  - {len(diff['warnings'])} warning(s)")
    else:
        print("DECISION: NO SIGNIFICANT DRIFT — safe to commit refreshed verdict")
    print("=" * 80)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("old", help="Path to OLD verdict JSON (typically archived)")
    parser.add_argument("new", help="Path to NEW verdict JSON (refreshed)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of formatted table")
    args = parser.parse_args()

    old_path = Path(args.old)
    new_path = Path(args.new)
    try:
        old = _load(old_path)
        old["__file"] = old_path.name
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot load OLD verdict {old_path}: {e}", file=sys.stderr)
        return 2
    try:
        new = _load(new_path)
        new["__file"] = new_path.name
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot load NEW verdict {new_path}: {e}", file=sys.stderr)
        return 2

    diff = compare(old, new)

    if args.json:
        print(json.dumps(diff, indent=2, default=str))
    else:
        _print_table(diff)

    return 1 if diff["needs_review"] else 0


if __name__ == "__main__":
    sys.exit(main())
