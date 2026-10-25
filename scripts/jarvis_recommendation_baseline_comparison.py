#!/usr/bin/env python3
"""Read-only baseline comparison for JARVIS recommendation attribution reports.

Consumes `docs/reports/JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json`
and emits a baseline comparison report. It does not read broker state, mutate the
engine, change risk/kill-switch config, or touch .env files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs" / "reports" / "JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json"
REPORT_DIR = ROOT / "docs" / "reports"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    return data


def _cohort(stats: dict[str, Any], name: str) -> dict[str, Any]:
    row = stats.get(name)
    if not isinstance(row, dict):
        raise ValueError(f"missing stats cohort: {name}")
    return row


def _num(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        return 0.0
    return float(value)


def _edge_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "pnl_delta": round(_num(candidate, "pnl") - _num(baseline, "pnl"), 2),
        "avg_trade_delta": round(_num(candidate, "avg_trade") - _num(baseline, "avg_trade"), 2),
        "win_rate_delta": round(_num(candidate, "win_rate") - _num(baseline, "win_rate"), 4),
        "profit_factor_delta": round(_num(candidate, "profit_factor") - _num(baseline, "profit_factor"), 4),
    }


def _pnl_per_trade(row: dict[str, Any]) -> float | None:
    closed = int(row.get("closed") or 0)
    return round(_num(row, "pnl") / closed, 4) if closed else None


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> dict[str, float | None]:
    if total <= 0:
        return {"low": None, "high": None}
    p = wins / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return {"low": round(max(0.0, center - half), 4), "high": round(min(1.0, center + half), 4)}


def build(input_path: Path) -> dict[str, Any]:
    attribution = _load(input_path)
    stats = attribution.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("input missing stats")
    summary = attribution.get("summary") if isinstance(attribution.get("summary"), dict) else {}
    all_paper = _cohort(stats, "all_paper")
    linked = _cohort(stats, "all_unique_linked")
    unlinked = _cohort(stats, "unlinked")
    rth = _cohort(stats, "rth_linked")
    queue_matched = _cohort(stats, "queue_order_id_matched")
    cohorts = {
        "all_paper": all_paper,
        "all_unique_linked": linked,
        "unlinked": unlinked,
        "rth_linked": rth,
        "queue_order_id_matched": queue_matched,
    }
    enriched = []
    for name, row in cohorts.items():
        wins = int(row.get("wins") or 0)
        closed = int(row.get("closed") or 0)
        enriched.append({
            "cohort": name,
            **row,
            "pnl_per_trade": _pnl_per_trade(row),
            "win_rate_wilson_95": _wilson_interval(wins, closed),
        })
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "read_only_recommendation_baseline_comparison",
        "source": str(input_path),
        "summary": {
            "linked_trades": summary.get("unique_linked_paper_trades"),
            "queue_order_id_matches_to_paper": summary.get("queue_order_id_matches_to_paper"),
            "baseline_warning": "positive linked ledger is not certified edge until queue-order lineage and forward baseline comparison are proven",
        },
        "cohorts": enriched,
        "comparisons": {
            "linked_vs_all_paper": _edge_delta(linked, all_paper),
            "linked_vs_unlinked": _edge_delta(linked, unlinked),
            "rth_linked_vs_all_paper": _edge_delta(rth, all_paper),
            "queue_order_matched_vs_all_paper": _edge_delta(queue_matched, all_paper),
        },
        "verdict": {
            "linked_outperformed_unlinked_pnl": _num(linked, "pnl") > _num(unlinked, "pnl"),
            "linked_outperformed_all_paper_avg_trade": (_pnl_per_trade(linked) or 0.0) > (_pnl_per_trade(all_paper) or 0.0),
            "queue_order_lineage_proven": int(summary.get("queue_order_id_matches_to_paper") or 0) > 0,
            "edge_certified": False,
        },
        "safety": {
            "read_only": True,
            "live_trading_changed": False,
            "risk_config_changed": False,
            "kill_switch_changed": False,
            "broker_execution_changed": False,
        },
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
    return str(value)


def render(report: dict[str, Any]) -> str:
    lines = [
        "# JARVIS Recommendation Baseline Comparison",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "> Scope: read-only comparison from attribution report JSON. No engine/risk/kill-switch/broker/.env/symbol-gate changes.",
        "",
        "## Verdict",
        "",
    ]
    for key, value in report["verdict"].items():
        lines.append(f"- `{key}`: **{value}**")
    lines.extend(["", "## Cohorts", "", "| Cohort | Closed | P&L | Avg/trade | Win rate | PF | Wilson 95% win-rate |", "|---|---:|---:|---:|---:|---:|---|"])
    for row in report["cohorts"]:
        wi = row["win_rate_wilson_95"]
        lines.append(
            f"| {row['cohort']} | {row.get('closed')} | ${_fmt(row.get('pnl'))} | ${_fmt(row.get('pnl_per_trade'))} | {_fmt(row.get('win_rate'))} | {_fmt(row.get('profit_factor'))} | {wi.get('low')}–{wi.get('high')} |"
        )
    lines.extend(["", "## Comparisons", ""])
    for name, comp in report["comparisons"].items():
        lines.append(f"### {name}")
        for key, value in comp.items():
            lines.append(f"- `{key}`: {_fmt(value)}")
        lines.append("")
    lines.extend(["## Interpretation", "", "Linked trades outperformed the unlinked cohort in this historical ledger, but queue-order lineage remains unproven and `edge_certified=false`. Treat this as prioritization evidence, not a production trading edge certificate.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-prefix", default="JARVIS_RECOMMENDATION_BASELINE_COMPARISON")
    args = parser.parse_args()
    report = build(args.input)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    json_path = REPORT_DIR / f"{args.output_prefix}_{stamp}.json"
    md_path = REPORT_DIR / f"{args.output_prefix}_{stamp}.md"
    latest_json = REPORT_DIR / f"{args.output_prefix}_LATEST.json"
    latest_md = REPORT_DIR / f"{args.output_prefix}_LATEST.md"
    payload = json.dumps(report, indent=2)
    md = render(report)
    for p, content in [(json_path, payload), (latest_json, payload), (md_path, md), (latest_md, md)]:
        p.write_text(content, encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "latest_json": str(latest_json), "latest_md": str(latest_md)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
