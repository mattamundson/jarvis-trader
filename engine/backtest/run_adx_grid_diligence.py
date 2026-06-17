#!/usr/bin/env python
"""
ADX threshold diligence sweep — 2026-06-17

Task 1 of post-discovery diligence on MGC H1 ADX-conditioned SMA trend.
Widens the ADX grid from {18,22,25} to {14,18,22,25,28,32} and re-runs
full WFO + gate-v2 for each threshold individually.

Safety: Research only. Writes to engine/data/discovery_2026_06_16/ ONLY.
        Does NOT write to gate_v2_verdicts/ or edge_ledger.jsonl.
        Does NOT modify signals.py, config.py, .env, or any live-routing code.
        Does NOT restart the engine or call any live endpoints.
        Does NOT git add/commit/push.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_adx_grid_diligence.py
    .venv/Scripts/python backtest/run_adx_grid_diligence.py --skip-validate
    .venv/Scripts/python backtest/run_adx_grid_diligence.py --adx 14,18,22,25,28,32
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — must run from engine/ directory
# ---------------------------------------------------------------------------
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

OUTPUT_DIR = engine_root / "data" / "discovery_2026_06_16"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Reuse the full discovery driver — it already has every helper we need
import backtest.run_discovery_2026_06_16 as disc  # noqa: E402  (must follow sys.path setup)

# ---------------------------------------------------------------------------
# ADX grid sweep
# ---------------------------------------------------------------------------

def run_single_adx_threshold(
    adx_threshold: float,
    df,
    symbol: str = "MGC",
) -> dict:
    """
    Run full WFO + gate-v2 for MGC H1 ADX-conditioned SMA trend at ONE fixed
    ADX threshold.  SMA params (fast=50/slow=120/atr_trail_mult=2.0) are the
    champion from the original H1 run.  We keep atr_trail_mult fixed at 2.0
    (the winning value) so the only variable is adx_threshold.

    Output JSON: MGC_H1_adx{NN}_sma_trend.json in OUTPUT_DIR.
    """
    label = f"H1_adx{int(adx_threshold)}_sma_trend"
    # Grid: fix the known-good SMA params, vary only atr around the champion
    # (keep atr variants to verify it's not atr sensitivity masking adx).
    grid = [
        {"fast": 50, "slow": 120, "atr_trail_mult": a, "adx_threshold": adx_threshold}
        for a in [1.5, 2.0]
    ]

    result = disc.run_hypothesis(
        label=label,
        symbol=symbol,
        signal_fn=disc.generate_adx_sma_trend_signals,
        param_grid=grid,
        train_months=6,
        test_months=2,   # matches champion WFO config
        step_months=1,
        df=df,
        min_oos_trades_per_window=1,
    )
    return result


def build_summary_table(results: list[dict]) -> str:
    """Render the comparison table as a plain-text string."""
    header = (
        f"{'adx_thresh':>10} | {'verdict':>12} | {'passed_via':>10} | "
        f"{'pf_ci_lower':>11} | {'p_edge':>6} | {'mc_dd%':>7} | "
        f"{'dsr':>6} | {'n_oos':>5} | block"
    )
    sep = "-" * len(header)
    rows = [header, sep]

    for r in results:
        g = r.get("gate_v2_metrics", {})
        cp = r.get("champion_params", {})
        row = (
            f"{cp.get('adx_threshold', '?'):>10} | "
            f"{r.get('verdict', '?'):>12} | "
            f"{r.get('passed_via') or 'N/A':>10} | "
            f"{g.get('pf_ci_lower') or 'n/a':>11} | "
            f"{g.get('p_edge') or 'n/a':>6} | "
            f"{g.get('mc_95th_dd_pct') or 'n/a':>7} | "
            f"{round(g.get('dsr') or 0, 4):>6} | "
            f"{g.get('total_oos_trades') or 0:>5} | "
            f"{r.get('primary_block') or ''}"
        )
        rows.append(row)

    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description="ADX diligence grid sweep 2026-06-17")
    parser.add_argument(
        "--adx",
        default="14,18,22,25,28,32",
        help="Comma-separated ADX thresholds to test (default: 14,18,22,25,28,32)",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip driver validation check (dangerous — use for re-runs after validated)",
    )
    args = parser.parse_args()

    adx_thresholds = [float(x.strip()) for x in args.adx.split(",")]
    print(f"\nADX diligence sweep — thresholds: {adx_thresholds}")
    print(f"Output dir: {OUTPUT_DIR}")

    # Step 1: Validate driver fidelity against MGC rank4 (same check as original sweep)
    if not args.skip_validate:
        print("\nStep 1: Validating driver against MGC rank4...")
        validated, _ = disc.run_validation()
        if not validated:
            print("\n[ABORT] Driver failed validation. Stopping.")
            sys.exit(1)
        print("[OK] Driver validated.\n")
    else:
        print("[WARN] Skipping driver validation per --skip-validate.\n")

    # Step 2: Load bars once (reused across all thresholds)
    print("Step 2: Loading MGC 1h bars...")
    df = disc.load_bars("MGC")

    # Step 3: Run each threshold
    results = []
    for adx_t in adx_thresholds:
        print(f"\n\n{'='*70}")
        print(f"ADX threshold = {adx_t}")
        print(f"{'='*70}")
        r = run_single_adx_threshold(adx_t, df, symbol="MGC")
        results.append(r)

    # Step 4: Print summary table
    print(f"\n\n{'='*70}")
    print("ADX DILIGENCE SUMMARY TABLE")
    print(f"{'='*70}")
    table = build_summary_table(results)
    print(table)

    # Step 5: Robustness verdict
    print(f"\n{'='*70}")
    print("ROBUSTNESS ASSESSMENT")
    print(f"{'='*70}")

    passing = [r for r in results if r.get("verdict") == "PASS"]
    failing = [r for r in results if r.get("verdict") != "PASS"]
    all_pass = len(failing) == 0
    majority_pass = len(passing) >= len(adx_thresholds) // 2 + 1

    print(f"Thresholds tested: {len(adx_thresholds)}")
    print(f"Passing gate-v2: {len(passing)} ({[r['champion_params']['adx_threshold'] for r in passing]})")
    print(f"Failing gate-v2: {len(failing)} ({[r['champion_params']['adx_threshold'] for r in failing if r.get('champion_params')]})")

    if all_pass:
        verdict_str = "ROBUST — edge persists across ALL tested ADX thresholds."
    elif majority_pass:
        verdict_str = "PARTIALLY ROBUST — edge survives majority of thresholds but not all."
    else:
        verdict_str = "CHERRY-PICKED — edge is NOT robust across the wider grid. adx=18 appears to overfit."

    print(f"\nVERDICT: {verdict_str}")

    # Step 6: Save consolidated summary JSON
    summary = {
        "diligence_type": "adx_wider_grid_sweep",
        "symbol": "MGC",
        "hypothesis": "H1_adx_sma_trend",
        "fixed_params": {"fast": 50, "slow": 120, "atr_trail_mult": 2.0},
        "adx_thresholds_tested": adx_thresholds,
        "results_summary": [
            {
                "adx_threshold": r.get("champion_params", {}).get("adx_threshold"),
                "verdict": r.get("verdict"),
                "passed_via": r.get("passed_via"),
                "primary_block": r.get("primary_block"),
                "pf_ci_lower": r.get("gate_v2_metrics", {}).get("pf_ci_lower"),
                "p_edge": r.get("gate_v2_metrics", {}).get("p_edge"),
                "mc_95th_dd_pct": r.get("gate_v2_metrics", {}).get("mc_95th_dd_pct"),
                "dsr": r.get("gate_v2_metrics", {}).get("dsr"),
                "n_oos_trades": r.get("gate_v2_metrics", {}).get("total_oos_trades"),
                "wfo_consistency": r.get("gate_v2_metrics", {}).get("wfo_consistency"),
            }
            for r in results
        ],
        "robustness_verdict": verdict_str,
        "n_pass": len(passing),
        "n_fail": len(failing),
    }

    summary_path = OUTPUT_DIR / "MGC_H1_adx_grid_diligence_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[WRITTEN] Summary JSON: {summary_path}")
    print(f"[WRITTEN] Per-threshold JSONs: {OUTPUT_DIR}/MGC_H1_adx{{NN}}_sma_trend.json")


if __name__ == "__main__":
    main()
