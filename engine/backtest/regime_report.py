"""Regime-conditional cross-strategy report.

Loads gate-v2 verdict JSONs, reads each verdict's ``regime_conditional`` field
(added in study_wfo_runner.py Step 3), and builds a cross-strategy table
flagging strategies whose TRENDING-regime PF materially exceeds the blended PF.

Hypothesis: the MGC trend edge is concentrated in trending regimes; some
"failures" are regime-averaging artefacts.

CLI usage:
    python backtest/regime_report.py

Writes:
    engine/data/regime_conditional_report.md
    engine/data/regime_conditional_report.json

This module is modelled exactly on family_fdr.py (same load_verdicts pattern,
same IO, same excluded-set handling for strategies that lack the field).

DIAGNOSTIC ONLY — does not affect any gate pass/fail decision.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

from backtest.family_fdr import load_verdicts  # reuse verbatim

logger = logging.getLogger("jarvis_trader.backtest.regime_report")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VERDICT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data", "gate_v2_verdicts"))
_REPORT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data"))

# "Materially exceeds": TRENDING PF >= blended PF + this threshold.
_TRENDING_EDGE_DELTA = 0.20


def _trending_pf(regime_conditional: dict) -> float | None:
    """Extract the TRENDING-regime profit factor from the breakdown, or None."""
    by_regime = regime_conditional.get("by_regime") or {}
    trending = by_regime.get("TRENDING") or {}
    pf = trending.get("profit_factor")
    if pf is None:
        return None
    return float(pf)


def _blended_pf(verdict: dict) -> float | None:
    """Extract the blended gate-v2 PF CI lower bound from the verdict, or None."""
    m = verdict.get("gate_v2_metrics") or {}
    v = m.get("pf_ci_lower")
    return float(v) if v is not None else None


def run(verdict_dir: str = _VERDICT_DIR) -> dict[str, Any]:
    """Build the regime-conditional cross-strategy report. Pure function (no writes)."""
    verdicts = load_verdicts(verdict_dir)

    strategies: list[dict] = []
    no_breakdown: list[dict] = []

    for v in verdicts:
        sid = v.get("_id", "unknown")
        rc = v.get("regime_conditional")

        if rc is None or "error" in rc or "by_regime" not in rc:
            no_breakdown.append({
                "id": sid,
                "gate_verdict": v.get("verdict"),
                "reason": "no regime_conditional field" if rc is None
                          else f"error: {rc.get('error', 'unknown')}",
            })
            continue

        blended = _blended_pf(v)
        trending_pf = _trending_pf(rc)
        by_regime = rc.get("by_regime", {})
        trending_info = by_regime.get("TRENDING") or {}
        range_info = by_regime.get("RANGE") or {}
        by_vol = rc.get("by_vol") or {}

        regime_edge = None
        if blended is not None and trending_pf is not None and not (
            trending_pf == float("inf")
        ):
            delta = trending_pf - blended
            regime_edge = delta >= _TRENDING_EDGE_DELTA
        elif trending_pf == float("inf"):
            regime_edge = True  # infinite PF in TRENDING is the strongest signal

        strategies.append({
            "id": sid,
            "symbol": v.get("symbol"),
            "family": v.get("family"),
            "gate_verdict": v.get("verdict"),
            "blended_pf_ci_lower": blended,
            "trending_pf": trending_pf,
            "trending_trades": trending_info.get("trades"),
            "trending_win_rate": trending_info.get("win_rate"),
            "range_pf": float(range_info.get("profit_factor", 0.0)) if range_info else None,
            "range_trades": range_info.get("trades"),
            "vol_low_pf": float((by_vol.get("LOW") or {}).get("profit_factor", 0.0))
                          if by_vol.get("LOW") else None,
            "vol_mid_pf": float((by_vol.get("MID") or {}).get("profit_factor", 0.0))
                          if by_vol.get("MID") else None,
            "vol_high_pf": float((by_vol.get("HIGH") or {}).get("profit_factor", 0.0))
                           if by_vol.get("HIGH") else None,
            "trending_edge_hypothesis": regime_edge,
            "classifier": rc.get("classifier", ""),
            "note": rc.get("note", ""),
        })

    trending_edge_ids = [s["id"] for s in strategies if s.get("trending_edge_hypothesis")]
    strategies_sorted = sorted(
        strategies,
        key=lambda s: (-(s["trending_pf"] or 0.0) if s["trending_pf"] != float("inf")
                       else -1e9),
    )

    return {
        "n_verdicts_total": len(verdicts),
        "n_with_breakdown": len(strategies),
        "n_no_breakdown": len(no_breakdown),
        "n_trending_edge_hypothesis": len(trending_edge_ids),
        "trending_edge_delta_threshold": _TRENDING_EDGE_DELTA,
        "strategies": strategies_sorted,
        "no_breakdown": no_breakdown,
        "trending_edge_ids": trending_edge_ids,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Regime-conditional performance — jarvis gate-v2 campaign",
        "",
        "**DIAGNOSTIC ONLY** — does not affect any gate pass/fail decision.",
        "",
        f"- Verdicts total: **{report['n_verdicts_total']}**",
        f"- With regime breakdown: **{report['n_with_breakdown']}**",
        f"- No breakdown (pre-existing verdicts): **{report['n_no_breakdown']}**",
        f"- Trending-edge hypothesis (TRENDING PF > blended + "
        f"{report['trending_edge_delta_threshold']:.2f}): "
        f"**{report['n_trending_edge_hypothesis']}**",
        "",
        "Hypothesis: some strategies whose blended PF is mediocre have a strong TRENDING "
        "sub-regime PF — regime-averaging is washing out the edge.",
        "",
        "| id | gate | blended_pf | TRENDING_pf | TRENDING_n | RANGE_pf | vol_L | vol_M | vol_H | TRENDING_EDGE? |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def _fmt(v) -> str:
        if v is None:
            return ""
        if v == float("inf"):
            return "inf"
        return f"{v:.3f}"

    for s in report["strategies"]:
        lines.append(
            "| {id} | {gv} | {bp} | {tp} | {tn} | {rp} | {vl} | {vm} | {vh} | {te} |".format(
                id=s["id"],
                gv=s["gate_verdict"] or "",
                bp=_fmt(s["blended_pf_ci_lower"]),
                tp=_fmt(s["trending_pf"]),
                tn=s["trending_trades"] if s["trending_trades"] is not None else "",
                rp=_fmt(s["range_pf"]),
                vl=_fmt(s["vol_low_pf"]),
                vm=_fmt(s["vol_mid_pf"]),
                vh=_fmt(s["vol_high_pf"]),
                te="**YES**" if s.get("trending_edge_hypothesis") else ".",
            )
        )

    if report["no_breakdown"]:
        lines += ["", "## No breakdown (no regime_conditional field)", ""]
        for e in report["no_breakdown"]:
            lines.append(f"- `{e['id']}` (gate={e['gate_verdict']}) — {e['reason']}")

    lines += [
        "",
        "## Interpretation",
        "",
        "- A `TRENDING_EDGE?=YES` means TRENDING-regime PF exceeds the blended "
        f"PF CI lower-bound by >= {report['trending_edge_delta_threshold']:.2f}.",
        "- This is a hypothesis generator, not a gate. Confirm with a regime-filtered "
        "walk-forward before drawing conclusions.",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regime-conditional cross-strategy report over gate-v2 verdicts"
    )
    parser.add_argument("--json", action="store_true", help="also print full JSON")
    parser.add_argument(
        "--verdict-dir", default=_VERDICT_DIR,
        help="Directory containing gate_v2 verdict JSON files",
    )
    args = parser.parse_args()

    report = run(verdict_dir=args.verdict_dir)

    md_path = os.path.join(_REPORT_DIR, "regime_conditional_report.md")
    json_path = os.path.join(_REPORT_DIR, "regime_conditional_report.json")
    os.makedirs(_REPORT_DIR, exist_ok=True)

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_markdown(report))
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_markdown(report))
    print(f"\n[written] {md_path}\n[written] {json_path}")


if __name__ == "__main__":
    main()
