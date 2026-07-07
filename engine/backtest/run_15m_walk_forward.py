"""
JARVIS TRADER — 15-minute Walk-Forward Validation Script

Validates 15m WFE for MCL, MNQ, and MES using shorter intraday windows.
Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_15m_walk_forward.py --symbol all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

KILL_THRESHOLDS = {"MCL": 0.40, "MNQ": 0.30, "MES": 0.40}
BASELINE_1H = {"MCL": 0.82, "MNQ": 0.57, "MES": 0.09}


def load_data(symbol: str, start: str, end: str) -> Optional[Any]:
    """Load 15m OHLCV data."""
    try:
        from backtest.data_loader import BacktestDataLoader

        df = BacktestDataLoader().load(symbol, start, end, "15m")
        if df is None or df.empty:
            print(f"[WARNING] No data for {symbol}")
            return None
        print(f"Loaded {len(df)} bars")
        return df
    except Exception as e:
        print(f"[WARNING] Load failed: {e}")
        return None


def run_validation(symbol: str, df: Any, multiplier: float, capital: float) -> Optional[dict]:
    """Run walk-forward validation."""
    try:
        from backtest.walk_forward import WalkForwardValidator

        validator = WalkForwardValidator(train_months=3, test_months=1, step_months=1)
        return validator.run(df, symbol, multiplier, capital, fast=True)
    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        return None


def compute_status(wfe: float, num_windows: int, threshold: float) -> str:
    """APPROVED if WFE >= threshold AND >= 5 windows, else OBSERVATION_ONLY."""
    return "APPROVED" if wfe >= threshold and num_windows >= 5 else "OBSERVATION_ONLY"


def format_table(results: dict) -> str:
    """Format results as markdown table."""
    lines = [
        "| Symbol | 15m WFE | 1h WFE | Threshold | Status | Windows |",
        "|--------|---------|--------|-----------|--------|---------|",
    ]
    for sym, data in results.items():
        if data is None:
            lines.append(
                f"| {sym} | ERROR | {BASELINE_1H.get(sym)} | {KILL_THRESHOLDS[sym]} | FAILED | N/A |"
            )
        else:
            s = data["summary"]
            wfe = s["wfe"]
            baseline = BASELINE_1H.get(sym, 0.0)
            arrow = "↑" if wfe > baseline else ("↓" if wfe < baseline else "=")
            lines.append(
                f"| {sym} | {wfe:.2f} {arrow} | {baseline:.2f} | {KILL_THRESHOLDS[sym]:.2f} | {data['status']} | {s['total_windows']} |"
            )
    return "\n".join(lines)


def build_report(results: dict, start: str, end: str, capital: float) -> str:
    """Build markdown report."""
    lines = [
        "# JARVIS TRADER — 15-minute Walk-Forward Validation Report",
        "",
        f"**Generated**: {datetime.now().isoformat()}",
        f"**Period**: {start} to {end} | **Capital**: ${capital:,.0f}",
        "",
        "## Overview",
        "Walk-forward WFE validation at 15m intraday (3mo train, 1mo test, 1mo step).",
        "",
        "## Results",
        "",
        format_table(results),
        "",
        "## Symbol Analysis",
        "",
    ]
    for sym in ["MCL", "MNQ", "MES"]:
        data = results.get(sym)
        lines.append(f"### {sym}")
        if data is None:
            lines.append("Status: DATA_ERROR")
        else:
            s = data["summary"]
            lines.append(f"- **15m WFE**: {s['wfe']:.4f}")
            lines.append(f"- **1h baseline**: {BASELINE_1H.get(sym):.2f}")
            lines.append(f"- **Status**: {data['status']}")
            lines.append(f"- **Windows**: {s['total_windows']}")
            lines.append(f"- **Avg OOS Return**: {s['avg_oos_return']*100:.2f}%")
            if sym == "MES":
                lines.append("- **Note**: 1h halted (WFE=0.09) — 15m tests intraday viability")
        lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for sym in ["MCL", "MNQ", "MES"]:
        data = results.get(sym)
        if data is None:
            lines.append(f"**{sym}**: Check data availability")
        elif data["status"] == "APPROVED":
            lines.append(f"**{sym}**: APPROVED — enable in paper_config")
        else:
            lines.append(f"**{sym}**: OBSERVATION_ONLY")
        lines.append("")
    return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="JARVIS TRADER — 15m Walk-Forward Validation")
    parser.add_argument("--symbol", default="all", help="Symbol: all|MCL|MNQ|MES")
    parser.add_argument("--start", default="2024-06-01", help="Start date")
    parser.add_argument("--end", default="2026-03-31", help="End date")
    parser.add_argument("--capital", type=float, default=25_000.0, help="Capital")
    parser.add_argument("--output", default=None, help="JSON output file")
    args = parser.parse_args()

    symbols = ["MCL", "MNQ", "MES"] if args.symbol.upper() == "ALL" else [args.symbol.upper()]
    for sym in symbols:
        if sym not in KILL_THRESHOLDS:
            print(f"[ERROR] Invalid symbol: {sym}")
            sys.exit(1)

    print("=" * 70)
    print("JARVIS TRADER — 15-minute Walk-Forward Validation")
    print("=" * 70)
    print(f"Symbols: {', '.join(symbols)} | Period: {args.start} to {args.end}")
    print("Windows: 3mo train, 1mo test, 1mo step")
    print("=" * 70)
    print()

    results = {}
    from backtest.data_loader import CONTRACT_MULTIPLIERS

    for symbol in symbols:
        print(f"\n[{symbol}] Running validation...")
        df = load_data(symbol, args.start, args.end)
        if df is None:
            results[symbol] = None
            continue

        multiplier = CONTRACT_MULTIPLIERS.get(symbol, 1.0)
        wf_result = run_validation(symbol, df, multiplier, args.capital)
        if wf_result is None:
            results[symbol] = None
            continue

        summary = wf_result["summary"]
        wfe = summary["wfe"]
        threshold = KILL_THRESHOLDS[symbol]
        status = compute_status(wfe, summary["total_windows"], threshold)
        results[symbol] = {"summary": summary, "status": status}

        print(f"[{symbol}] WFE={wfe:.4f} | Threshold={threshold:.2f} | Status={status}")

    print("\n" + "=" * 70)
    for sym in symbols:
        data = results.get(sym)
        status = data["status"] if data else "FAILED"
        wfe = f"{data['summary']['wfe']:.4f}" if data else "N/A"
        print(f"{sym}: {status:20} (WFE={wfe})")

    report = build_report(results, args.start, args.end, args.capital)
    report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "sprint15_15m_validation.md").write_text(report)
    print(f"\nReport saved: {report_dir / 'sprint15_15m_validation.md'}")

    if args.output:
        json_results = {}
        for sym, data in results.items():
            if data:
                json_results[sym] = {"summary": data["summary"], "status": data["status"]}
            else:
                json_results[sym] = {"status": "FAILED"}
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(json_results, f, indent=2)
        print(f"JSON saved: {args.output}")

    print("=" * 70)


if __name__ == "__main__":
    main()
