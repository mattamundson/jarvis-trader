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
    .venv/Scripts/python -m backtest.compare_verdicts old.json new.json --alert-on-rating-drop
    .venv/Scripts/python -m backtest.compare_verdicts old.json new.json --config engine/data/compare_verdicts_config.yaml

Exit codes:
    0 — no significant drift; safe to commit refreshed verdict
    1 — verdict transition or significant param drift; manual review needed
        (with --alert-on-rating-drop: exit 1 ONLY on degradation, not improvements)
    2 — file read or parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backtest.verdict_schema import (
    VerdictSchema,  # noqa: F401 — re-exported for callers
    load_verdict_validated,  # noqa: F401 — public API
)

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


@dataclass
class ThresholdConfig:
    """Thresholds controlling compare() sensitivity. Loadable from YAML per-symbol."""

    param_drift: float = PARAM_DRIFT_THRESHOLD
    rating_drop_pf_ci: float = 0.15  # pf_ci drop fraction that triggers rating_drop
    rating_drop_dsr: float = 0.20  # dsr drop fraction that triggers rating_drop
    rating_drop_mc_dd: float = 0.50  # mc_dd rise fraction that triggers rating_drop


_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "data" / "compare_verdicts_config.yaml"


def _load_config(path: Path | None = None, symbol: str | None = None) -> ThresholdConfig:
    """Load ThresholdConfig from YAML; returns dataclass defaults if file absent or PyYAML unavailable.

    YAML format::

        default:
          param_drift_threshold: 0.10
          rating_drop_pf_ci: 0.15
          rating_drop_dsr: 0.20
          rating_drop_mc_dd: 0.50
        MES:
          param_drift_threshold: 0.15
    """
    resolved = path if path is not None else _DEFAULT_CONFIG_PATH
    if not resolved.exists():
        return ThresholdConfig()
    try:
        import yaml
    except ImportError:
        return ThresholdConfig()
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ThresholdConfig()
    base: dict = data.get("default", {}) or {}
    sym_override: dict = (data.get(symbol, {}) or {}) if symbol else {}
    merged = {**base, **sym_override}
    cfg = ThresholdConfig()
    if "param_drift_threshold" in merged:
        cfg.param_drift = float(merged["param_drift_threshold"])
    if "rating_drop_pf_ci" in merged:
        cfg.rating_drop_pf_ci = float(merged["rating_drop_pf_ci"])
    if "rating_drop_dsr" in merged:
        cfg.rating_drop_dsr = float(merged["rating_drop_dsr"])
    if "rating_drop_mc_dd" in merged:
        cfg.rating_drop_mc_dd = float(merged["rating_drop_mc_dd"])
    return cfg


def _load(path: Path) -> dict[str, Any]:
    """Load a verdict JSON, returning the parsed dict or raising FileNotFoundError/JSONDecodeError."""
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(text)
    return result


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


def _is_rating_drop(diff: dict[str, Any], cfg: ThresholdConfig | None = None) -> bool:
    """Return True if the new verdict represents a degradation vs. the old one.

    Degradation criteria (any one is sufficient):
    - Verdict dropped: PASS -> FAIL or PASS -> INSUFFICIENT_SAMPLE
    - Path downgraded: PASS-core -> PASS-alt (loss of core margin)
    - pf_ci_lower fell by more than cfg.rating_drop_pf_ci (default 15%)
    - dsr fell by more than cfg.rating_drop_dsr (default 20%)
    - mc_95th_dd_pct rose by more than cfg.rating_drop_mc_dd (default 50%)
    """
    if cfg is None:
        cfg = ThresholdConfig()
    # Verdict-level drop
    old_v = diff.get("old_verdict")
    new_v = diff.get("new_verdict")
    if old_v == "PASS" and new_v in ("FAIL", "INSUFFICIENT_SAMPLE"):
        return True
    # Core -> alt downgrade
    old_via = diff.get("old_passed_via")
    new_via = diff.get("new_passed_via")
    if old_via == "core" and new_via == "alt":
        return True

    # Metric degradation
    deltas = diff.get("metric_deltas", {})
    pf_d = deltas.get("pf_ci")
    if (
        pf_d
        and isinstance(pf_d.get("old"), (int, float))
        and isinstance(pf_d.get("delta"), (int, float))
    ):
        if pf_d["old"] > 0 and pf_d["delta"] / pf_d["old"] < -cfg.rating_drop_pf_ci:
            return True
    dsr_d = deltas.get("dsr")
    if (
        dsr_d
        and isinstance(dsr_d.get("old"), (int, float))
        and isinstance(dsr_d.get("delta"), (int, float))
    ):
        if dsr_d["old"] > 0 and dsr_d["delta"] / dsr_d["old"] < -cfg.rating_drop_dsr:
            return True
    mc_d = deltas.get("mc_dd%")
    if (
        mc_d
        and isinstance(mc_d.get("old"), (int, float))
        and isinstance(mc_d.get("delta"), (int, float))
    ):
        if mc_d["old"] > 0 and mc_d["delta"] / mc_d["old"] > cfg.rating_drop_mc_dd:
            return True

    return False


def compare(old: dict, new: dict, cfg: ThresholdConfig | None = None) -> dict[str, Any]:
    """Compute a structured diff between two verdicts."""
    if cfg is None:
        cfg = ThresholdConfig()
    # Top-level identity
    summary: dict[str, Any] = {
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
                    "exceeds_threshold": _is_drifted(ov, nv, cfg.param_drift),
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
    summary["rating_drop"] = _is_rating_drop(summary, cfg)

    return summary


def _print_table(diff: dict[str, Any], cfg: ThresholdConfig | None = None) -> None:
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
    if diff["rating_drop"]:
        print("ALERT: RATING DROP DETECTED")
        if diff["verdict_transition"] != "no transition":
            print(f"  - Verdict: {diff['verdict_transition']}")
        deltas = diff.get("metric_deltas", {})
        for label in ("pf_ci", "dsr", "mc_dd%"):
            d = deltas.get(label)
            if d and isinstance(d.get("delta"), (int, float)) and d["delta"] != 0:
                print(f"  - {label}: {d['old']} -> {d['new']} ({d['delta']:+.4f})")
    if diff["needs_review"]:
        if not diff["rating_drop"]:
            print("DECISION: MANUAL REVIEW NEEDED")
        if diff["verdict_transition"] != "no transition":
            print(f"  - Verdict changed: {diff['verdict_transition']}")
        drifted = [d for d in diff["champion_drift"] if d.get("exceeds_threshold")]
        if drifted:
            _cfg = cfg if cfg is not None else ThresholdConfig()
            print(f"  - {len(drifted)} champion param(s) drifted >{_cfg.param_drift * 100:.0f}%")
        if diff["warnings"]:
            print(f"  - {len(diff['warnings'])} warning(s)")
    else:
        if not diff["rating_drop"]:
            print("DECISION: NO SIGNIFICANT DRIFT — safe to commit refreshed verdict")
    print("=" * 80)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("old", help="Path to OLD verdict JSON (typically archived)")
    parser.add_argument("new", help="Path to NEW verdict JSON (refreshed)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of formatted table")
    parser.add_argument(
        "--alert-on-rating-drop",
        action="store_true",
        help=(
            "Exit with code 1 ONLY when a rating drop is detected (PASS->FAIL, "
            "core->alt, or >15%% pf_ci / >20%% dsr / >50%% mc_dd degradation). "
            "Improvements and neutral param drift do NOT trigger exit 1. "
            "Useful for CI gates that should only block on degradation."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="YAML",
        help=(
            "Path to threshold config YAML. Defaults to "
            "engine/data/compare_verdicts_config.yaml if present. "
            "Supports per-symbol overrides under a key matching the symbol name."
        ),
    )
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

    config_path = Path(args.config) if getattr(args, "config", None) else None
    symbol = old.get("symbol") or new.get("symbol")
    cfg = _load_config(config_path, symbol)

    diff = compare(old, new, cfg)

    if args.json:
        print(json.dumps(diff, indent=2, default=str))
    else:
        _print_table(diff, cfg)

    if getattr(args, "alert_on_rating_drop", False):
        return 1 if diff["rating_drop"] else 0
    return 1 if diff["needs_review"] else 0


if __name__ == "__main__":
    sys.exit(main())
