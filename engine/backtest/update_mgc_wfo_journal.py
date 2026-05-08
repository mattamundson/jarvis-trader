"""Update the MGC WFO + p_edge rolling journal.

Appends one row to ``engine/data/mgc_wfo_journal.csv`` from the current
``MGC_trend_rank4.json`` verdict. Run after every backtest refresh to
keep a time-series record suitable for regime-shift detection.

Usage::

    cd engine
    python backtest/update_mgc_wfo_journal.py

The journal accumulates rows over weeks/months; a rising p_edge and
stable wfo_consistency signal a healthy regime, while a dropping
fixed_params_min_pf signals a weakening edge before the gate v2 verdict
would flip to FAIL.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
VERDICT_PATH = ENGINE_ROOT / "data" / "gate_v2_verdicts" / "MGC_trend_rank4.json"
JOURNAL_PATH = ENGINE_ROOT / "data" / "mgc_wfo_journal.csv"

FIELDNAMES = [
    "recorded_at",
    "verdict",
    "passed_via",
    "wfo_consistency",
    "pf_ci_lower",
    "p_edge",
    "mc_95th_dd_pct",
    "dsr",
    "fixed_params_min_pf",
    "fixed_params_mean_pf",
    "n_combos_with_trades",
    "champion_fast",
    "champion_slow",
    "champion_atr",
]


def load_verdict() -> dict:
    if not VERDICT_PATH.exists():
        raise FileNotFoundError(f"Verdict not found: {VERDICT_PATH}")
    with open(VERDICT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def build_row(d: dict) -> dict:
    m = d.get("gate_v2_metrics", {})
    cp = d.get("champion_params", {})
    return {
        "recorded_at": d.get("created_at", datetime.now(timezone.utc).isoformat()),
        "verdict": d.get("verdict", ""),
        "passed_via": d.get("passed_via", ""),
        "wfo_consistency": m.get("wfo_consistency", ""),
        "pf_ci_lower": m.get("pf_ci_lower", ""),
        "p_edge": m.get("p_edge", ""),
        "mc_95th_dd_pct": m.get("mc_95th_dd_pct", ""),
        "dsr": m.get("dsr", ""),
        "fixed_params_min_pf": m.get("fixed_params_min_pf", ""),
        "fixed_params_mean_pf": m.get("fixed_params_mean_pf", ""),
        "n_combos_with_trades": m.get("n_combos_with_trades", ""),
        "champion_fast": cp.get("fast", ""),
        "champion_slow": cp.get("slow", ""),
        "champion_atr": cp.get("atr_trail_mult", ""),
    }


def append_to_journal(row: dict) -> None:
    write_header = not JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    verdict = load_verdict()
    row = build_row(verdict)
    append_to_journal(row)
    print(
        f"MGC WFO journal updated: verdict={row['verdict']} | "
        f"pf_ci_lower={row['pf_ci_lower']} | p_edge={row['p_edge']} | "
        f"mc_dd={row['mc_95th_dd_pct']}% | wfo={row['wfo_consistency']}"
    )
    print(f"  Journal: {JOURNAL_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
