"""
JARVIS TRADER — COHEN-MES Composite Backtest Runner
====================================================

Runs the composite MES strategy (STC + ORB + VWAP, regime-adaptive)
through the standard walk-forward backtester.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_composite_backtest.py
    .venv/Scripts/python backtest/run_composite_backtest.py --start 2024-06-01 --end 2026-03-31
    .venv/Scripts/python backtest/run_composite_backtest.py --threshold 0.3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("run_composite_backtest")

# Add engine root to path
_ENGINE_DIR = Path(__file__).parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# MES Backtest Parameters (fallback for instruments without paper_config)
MES_BACKTEST_PARAMS = {
    "stc_os": 15,
    "stc_ob": 83,
    "stop_atr_mult": 0.90,
    "t1_atr_mult": 1.50,
    "t2_atr_mult": 2.618,
    "t3_atr_mult": 4.00,
}

# Composite approval thresholds by symbol
COMPOSITE_THRESHOLDS = {
    "MCL": 0.40,
    "MNQ": 0.40,
    "MES": 0.40,
}


def main():
    parser = argparse.ArgumentParser(
        description="COHEN-MES Composite Strategy Backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", default="MES", help="Symbol to backtest")
    parser.add_argument(
        "--all-instruments",
        action="store_true",
        help="Run composite backtest for all instruments (MCL, MNQ, MES)",
    )
    parser.add_argument("--start", default="2024-06-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-03-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", default="1h", help="Data interval")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.55,
        help="Composite score threshold for entry (0.3-0.6)",
    )
    parser.add_argument(
        "--band-mult",
        type=float,
        default=3.0,
        help="VWAP band ATR multiplier",
    )
    parser.add_argument("--output", default=None, help="Save JSON results to file")
    args = parser.parse_args()

    # If --all-instruments is set, it takes precedence over --symbol
    if args.all_instruments:
        return _run_all_instruments(args)
    else:
        return _run_single_instrument(args)


def _run_single_instrument(args):
    """Run composite backtest for a single symbol."""
    print("=" * 60)
    print("COHEN-MES COMPOSITE STRATEGY BACKTEST")
    print("=" * 60)
    print(f"Symbol   : {args.symbol}")
    print(f"Period   : {args.start} → {args.end}")
    print(f"Interval : {args.interval}")
    print(f"Capital  : ${args.capital:,.0f}")
    print(f"Risk     : {args.risk:.1%} per trade")
    print(f"Threshold: {args.threshold}")
    print(f"VWAP band: {args.band_mult}×ATR")
    print("-" * 60)

    # ── Imports ───────────────────────────────────────────────────────────
    try:
        from backtest.backtester import Backtester
        from backtest.composite_signals import generate_composite_signals
        from backtest.contract_specs import get_spec
        from backtest.data_loader import BacktestDataLoader
    except ImportError as e:
        print(f"[ERROR] Import failed: {e}")
        print(
            "Run from the engine/ directory: cd engine && .venv/Scripts/python -m backtest.run_composite_backtest"
        )
        sys.exit(1)

    # ── Load Data ─────────────────────────────────────────────────────────
    loader = BacktestDataLoader()
    print(f"Loading {args.symbol} data from Yahoo Finance...")
    try:
        df = loader.load(args.symbol, args.start, args.end, args.interval)
    except Exception as e:
        print(f"[ERROR] Data load failed for {args.symbol}: {e}")
        return None

    if df is None or df.empty:
        print(f"[ERROR] No data returned for {args.symbol}")
        return None

    print(f"Loaded {len(df)} bars ({args.start} → {args.end})")
    print(f"Price range: ${df['close'].min():.2f} – ${df['close'].max():.2f}")

    # ── Get STC Parameters for Symbol ────────────────────────────────────
    try:
        from backtest.paper_config import PAPER_CONFIGS

        symbol_config = PAPER_CONFIGS.get(args.symbol)
        if symbol_config:
            stc_params = symbol_config.get("stc_params", {})
            stc_os = stc_params.get("stc_os", None)
            stc_ob = stc_params.get("stc_ob", None)
        else:
            # Fallback: use MES_BACKTEST_PARAMS
            stc_os = MES_BACKTEST_PARAMS.get("stc_os", None)
            stc_ob = MES_BACKTEST_PARAMS.get("stc_ob", None)
    except ImportError:
        stc_os = MES_BACKTEST_PARAMS.get("stc_os", None)
        stc_ob = MES_BACKTEST_PARAMS.get("stc_ob", None)

    # ── Generate Composite Signals ────────────────────────────────────────
    print("\nGenerating composite signals (STC + ORB + VWAP, adaptive regime)...")
    print(f"Using STC params: OS={stc_os}, OB={stc_ob}")
    df = generate_composite_signals(
        df,
        symbol=args.symbol,
        band_mult=args.band_mult,
        entry_threshold=args.threshold,
        stc_oversold=stc_os,
        stc_overbought=stc_ob,
    )

    n_entry = (df["entry_signal"] == "ENTRY_NOW").sum()
    n_long = ((df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BULL")).sum()
    n_short = ((df["entry_signal"] == "ENTRY_NOW") & (df["bias"] == "STRONG_BEAR")).sum()
    n_volatile = (df["entry_signal"] == "COMPOSITE_VOLATILE_BLOCK").sum()
    regime_dist = df.get("composite_regime", df.get("regime_type", None))

    print(
        f"Signals: {n_entry} entries ({n_long} LONG, {n_short} SHORT), {n_volatile} volatile-blocked"
    )
    if regime_dist is not None:
        print(f"Regime distribution: {regime_dist.value_counts().to_dict()}")

    # Signal contribution breakdown
    if "stc_contrib" in df.columns:
        n_stc = int(df["stc_contrib"].sum())
        n_orb = int(df["orb_contrib"].sum())
        n_vwap = int(df["vwap_contrib"].sum())
        print(f"Signal contributions: STC={n_stc} ORB={n_orb} VWAP={n_vwap}")

    if n_entry == 0:
        print("\n[WARNING] No entries generated. Try lowering --threshold (e.g. 0.3).")
        print("Hint: In RANGING regime (typical for MES), VWAP must fire for score≥0.4.")
        print("If VWAP signals are absent, try --band-mult 1.2 for tighter bands.")

    # ── Run Backtest ──────────────────────────────────────────────────────
    print("\nRunning walk-forward simulation...")
    multiplier = loader.get_multiplier(args.symbol)
    print(f"Contract multiplier: {multiplier}")

    # Per-symbol commission (was a flat 2.50 regardless of --symbol / the
    # --all-instruments MCL/MNQ/MES loop — canonical rates live in
    # contract_specs.CONTRACT_SPECS).
    commission_per_contract = get_spec(args.symbol).commission
    backtester = Backtester(
        initial_capital=args.capital,
        risk_per_trade=args.risk,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        commission_per_contract=commission_per_contract,
        slippage_ticks=1,
    )

    result = backtester.run(df, args.symbol, multiplier)

    # ── Print Results ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(result.summary())
    print("=" * 60)

    # Key metrics — win_rate, total_return_pct, max_drawdown_pct are FRACTIONS
    # (0.199 == 19.9%). Use {:.1%} to format, not {:.1f}% which would miss the ×100.
    r = result.to_dict()
    sharpe = r.get("sharpe_ratio", 0.0)
    pf = r.get("profit_factor", 0.0)
    wr = r.get("win_rate", 0.0)
    ret = r.get("total_return_pct", 0.0)
    max_dd = r.get(
        "max_drawdown_pct", 0.0
    )  # FIX: was "max_drawdown" which never existed → always 0
    n_trades = r.get("total_trades", 0)

    print("\nKEY METRICS (COHEN-MES Composite):")
    print(
        f"  Sharpe Ratio  : {sharpe:.2f}  {'✓ TARGET MET' if sharpe >= 2.0 else '✗ Target: ≥2.0'}"
    )
    print(f"  Profit Factor : {pf:.2f}  {'✓' if pf >= 2.0 else '✗ Target: ≥2.0'}")
    print(f"  Win Rate      : {wr:.1%}")
    print(f"  Total Return  : {ret:+.1%}")
    print(f"  Max Drawdown  : {max_dd:.1%}")
    print(f"  Total Trades  : {n_trades}")

    # WFE (Walk-Forward Efficiency) estimate
    wfe = _estimate_wfe(df, args.symbol, multiplier, backtester, args.risk)
    if wfe is not None:
        print(f"  WFE estimate  : {wfe:.2f}  {'✓' if wfe >= 0.40 else '✗ Target: ≥0.40'}")

    # Overall verdict
    print()
    if sharpe >= 2.0 and pf >= 2.0 and n_trades >= 20:
        print("STATUS: ✓ APPROVED — Sharpe≥2.0, PF≥2.0, sufficient trades")
        print("        Ready for paper trading deployment")
    elif sharpe >= 1.5:
        print("STATUS: ⚠ MARGINAL — Sharpe≥1.5 but below 2.0 target")
        print("        Try: --threshold 0.3 or --band-mult 1.2 for more signals")
    else:
        print("STATUS: ✗ NEEDS TUNING — Below target")
        print("        Recommendations:")
        if n_trades < 20:
            print("          - Too few trades: lower --threshold to 0.3")
            print("          - Or narrow VWAP bands: --band-mult 1.2")
        if wr < 0.30:
            print("          - Low win rate: tighten entry threshold")
        print("          - Check regime distribution — pure RANGING favors VWAP")

    # ── Save Results ──────────────────────────────────────────────────────
    engine_root = Path(__file__).parent.parent
    results_dir = engine_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    auto_filename = f"composite_{args.symbol}_{args.interval}_{args.start}_{args.end}.json"
    auto_path = results_dir / auto_filename

    result_data = result.to_dict()
    json_payload = {
        "strategy": "COHEN-MES Composite (STC+ORB+VWAP)",
        "symbol": args.symbol,
        "interval": args.interval,
        "start": args.start,
        "end": args.end,
        "threshold": args.threshold,
        "band_mult": args.band_mult,
        "n_trades": n_trades,
        "win_rate": round(wr, 4),
        "profit_factor": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "total_return": round(ret, 4),
        "max_drawdown": round(max_dd, 4),
        "wfe": wfe,
        "approved": sharpe >= 2.0 and pf >= 2.0 and n_trades >= 20,
        "signal_contributions": {
            "stc": int(df.get("stc_contrib", pd.Series(False)).sum()) if hasattr(df, "get") else 0,
            "orb": int(df.get("orb_contrib", pd.Series(False)).sum()) if hasattr(df, "get") else 0,
            "vwap": (
                int(df.get("vwap_contrib", pd.Series(False)).sum()) if hasattr(df, "get") else 0
            ),
        },
        "regime_distribution": (
            regime_dist.value_counts().to_dict() if regime_dist is not None else {}
        ),
        "trades": [
            {
                "entry_date": str(t.get("entry_date", "")),
                "exit_date": str(t.get("exit_date", "")),
                "direction": t.get("direction", ""),
                "pnl": round(t.get("pnl", 0), 2),
            }
            for t in (result_data.get("trades", []) or [])
        ],
    }

    if args.output:
        save_path = Path(args.output)
    else:
        save_path = auto_path

    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    print(f"\nResults saved to: {save_path}")

    # Update SUMMARY.md
    _update_summary(results_dir, args, json_payload, sharpe, pf, wr, n_trades, max_dd, wfe)

    return json_payload


def _run_all_instruments(args):
    """Run composite backtest for all instruments (MCL, MNQ, MES)."""
    instruments = ["MCL", "MNQ", "MES"]
    results = {}

    print("=" * 60)
    print("COMPOSITE BACKTEST — ALL INSTRUMENTS")
    print("=" * 60)
    print(f"Period   : {args.start} → {args.end}")
    print(f"Capital  : ${args.capital:,.0f}")
    print(f"Risk     : {args.risk:.1%} per trade")
    print(f"Threshold: {args.threshold}")
    print(f"VWAP band: {args.band_mult}×ATR")
    print("-" * 60)

    for symbol in instruments:
        print(f"\nRunning composite backtest for {symbol}...")
        print("=" * 60)

        # Create args copy with specific symbol
        symbol_args = argparse.Namespace(
            symbol=symbol,
            all_instruments=False,
            start=args.start,
            end=args.end,
            interval=args.interval,
            capital=args.capital,
            risk=args.risk,
            threshold=args.threshold,
            band_mult=args.band_mult,
            output=None,
        )

        try:
            result = _run_single_instrument(symbol_args)
            results[symbol] = result
        except Exception as e:
            print(f"[WARNING] Backtest failed for {symbol}: {e}")
            results[symbol] = None

    # ── Print Summary Table ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("COMPOSITE BACKTEST SUMMARY — ALL INSTRUMENTS")
    print("=" * 60)

    summary_data = []
    for symbol in instruments:
        result = results.get(symbol)
        if result is None:
            summary_data.append(
                {"Symbol": symbol, "Status": "ERROR", "WFE": "N/A", "Recommendation": "DATA_ERROR"}
            )
        else:
            wfe = result.get("wfe", None)
            threshold = COMPOSITE_THRESHOLDS.get(symbol, 0.40)
            if wfe is None:
                recommendation = "INSUFFICIENT_DATA"
            elif wfe >= threshold:
                recommendation = "ENABLE_COMPOSITE"
            else:
                recommendation = "BELOW_THRESHOLD"

            wfe_display = f"{wfe:.2f}" if wfe is not None else "N/A"
            summary_data.append(
                {
                    "Symbol": symbol,
                    "Status": "OK",
                    "WFE": wfe_display,
                    "Threshold": f"{threshold:.2f}",
                    "Recommendation": recommendation,
                }
            )

    # Print as table
    if summary_data:
        print(
            f"\n{'Symbol':<8} {'Status':<12} {'WFE':<10} {'Threshold':<12} {'Recommendation':<20}"
        )
        print("-" * 62)
        for row in summary_data:
            print(
                f"{row['Symbol']:<8} {row['Status']:<12} {row['WFE']:<10} {row['Threshold']:<12} {row['Recommendation']:<20}"
            )

    # ── Print Configuration Changes ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CONFIGURATION CHANGES (if approved)")
    print("=" * 60)
    for symbol in instruments:
        result = results.get(symbol)
        if result is None:
            continue
        wfe = result.get("wfe", None)
        if wfe is None:
            continue
        threshold = COMPOSITE_THRESHOLDS.get(symbol, 0.40)
        if wfe >= threshold:
            print(f"\n# To enable composite for {symbol}, change paper_config.py:")
            print(f"# {symbol}_PAPER_CONFIG['composite'] = True  # WFE={wfe:.2f} APPROVED")

    # ── Write Report ──────────────────────────────────────────────────────
    _write_composite_report(results, instruments, args)

    return results


def _write_composite_report(results, instruments, args):
    """Write composite backtest report to markdown."""
    engine_root = Path(__file__).parent.parent
    reports_dir = engine_root / "backtest" / ".." / "docs" / "reports"
    reports_dir = reports_dir.resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / "sprint15_composite_mcl_mnq_mes.md"

    lines = []
    lines.append("# Sprint 15: Composite Backtest Report (MCL, MNQ, MES)")
    lines.append("")
    lines.append(f"**Date**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Period**: {args.start} → {args.end}")
    lines.append(f"**Interval**: {args.interval}")
    lines.append("")

    lines.append("## Overview")
    lines.append("")
    lines.append("This report presents walk-forward efficiency (WFE) for the composite strategy")
    lines.append("(STC + ORB + VWAP) across three instruments: MCL, MNQ, and MES.")
    lines.append("")

    # Per-symbol results
    lines.append("## Per-Symbol Results")
    lines.append("")

    for symbol in instruments:
        lines.append(f"### {symbol}")
        lines.append("")

        result = results.get(symbol)
        if result is None:
            lines.append("**Status**: ERROR — data load or backtest failed")
            lines.append("")
            continue

        wfe = result.get("wfe", None)
        threshold = COMPOSITE_THRESHOLDS.get(symbol, 0.40)
        pf = result.get("profit_factor", 0.0)
        sharpe = result.get("sharpe", 0.0)
        wr = result.get("win_rate", 0.0)
        n_trades = result.get("n_trades", 0)
        max_dd = result.get(
            "max_drawdown", 0.0
        )  # from json_payload line 272 — writer-side key is "max_drawdown"

        if wfe is None:
            recommendation = "INSUFFICIENT_DATA"
        elif wfe >= threshold:
            recommendation = "ENABLE_COMPOSITE"
        else:
            recommendation = "BELOW_THRESHOLD"

        wfe_str = f"{wfe:.2f}" if wfe is not None else "N/A"
        lines.append(f"**WFE**: {wfe_str}")
        lines.append(f"**Threshold**: {threshold:.2f}")
        lines.append(f"**Recommendation**: {recommendation}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Profit Factor | {pf:.2f} |")
        lines.append(f"| Sharpe Ratio | {sharpe:.2f} |")
        lines.append(f"| Win Rate | {wr:.1%} |")
        lines.append(f"| Total Trades | {n_trades} |")
        lines.append(f"| Max Drawdown | {max_dd:.1%} |")
        lines.append("")

    lines.append("## Comparison Table")
    lines.append("")
    lines.append("| Symbol | WFE | Threshold | Status | Recommendation |")
    lines.append("|--------|-----|-----------|--------|-----------------|")

    for symbol in instruments:
        result = results.get(symbol)
        if result is None:
            lines.append(f"| {symbol} | ERROR | - | ERROR | CHECK_DATA |")
        else:
            wfe = result.get("wfe", None)
            threshold = COMPOSITE_THRESHOLDS.get(symbol, 0.40)
            if wfe is None:
                recommendation = "INSUFFICIENT_DATA"
            elif wfe >= threshold:
                recommendation = "ENABLE_COMPOSITE"
            else:
                recommendation = "BELOW_THRESHOLD"
            wfe_str = f"{wfe:.2f}" if wfe is not None else "N/A"
            lines.append(f"| {symbol} | {wfe_str} | {threshold:.2f} | OK | {recommendation} |")

    lines.append("")
    lines.append("## Recommendations")
    lines.append("")

    for symbol in instruments:
        result = results.get(symbol)
        if result is None:
            continue
        wfe = result.get("wfe", None)
        if wfe is None:
            continue
        threshold = COMPOSITE_THRESHOLDS.get(symbol, 0.40)
        if wfe >= threshold:
            lines.append(f"### {symbol} — ENABLE_COMPOSITE")
            lines.append("")
            lines.append(f"WFE of {wfe:.2f} exceeds threshold of {threshold:.2f}.")
            lines.append("To enable composite for trading, update paper_config.py:")
            lines.append("")
            lines.append("```python")
            lines.append(f"{symbol}_PAPER_CONFIG['composite'] = True")
            lines.append("```")
            lines.append("")

    # Write file
    report_content = "\n".join(lines)
    with open(report_path, "w") as f:
        f.write(report_content)

    print(f"\nReport written to: {report_path}")
    return report_path


def _estimate_wfe(df, symbol, multiplier, backtester_template, risk):
    """
    Rough WFE: IS Sharpe vs OOS Sharpe ratio.
    Split the data 75%/25% and compare.
    """
    try:
        split = int(len(df) * 0.75)
        if split < 50:
            return None
        df_is = df.iloc[:split].copy()
        df_oos = df.iloc[split:].copy()

        bt_is = type(backtester_template)(
            initial_capital=backtester_template.initial_capital,
            risk_per_trade=risk,
        )
        bt_oos = type(backtester_template)(
            initial_capital=backtester_template.initial_capital,
            risk_per_trade=risk,
        )
        r_is = bt_is.run(df_is, symbol, multiplier)
        r_oos = bt_oos.run(df_oos, symbol, multiplier)

        sharpe_is = r_is.to_dict().get("sharpe_ratio", 0)
        sharpe_oos = r_oos.to_dict().get("sharpe_ratio", 0)

        if sharpe_is <= 0:
            return 0.0
        return round(sharpe_oos / sharpe_is, 2)
    except Exception:
        return None


def _update_summary(results_dir, args, payload, sharpe, pf, wr, n_trades, max_dd, wfe):
    """Append result to SUMMARY.md."""
    summary_path = results_dir / "SUMMARY.md"
    status = "APPROVED" if payload.get("approved") else "NEEDS TUNING"
    wfe_str = f"{wfe:.2f}" if wfe is not None else "N/A"

    entry = f"""
## COHEN-MES Composite ({args.interval}) — {args.start} to {args.end}
Strategy: STC+ORB+VWAP regime-adaptive composite (threshold={args.threshold}, band_mult={args.band_mult})
Trades: {n_trades} | Win Rate: {wr:.1%} | PF: {pf:.2f} | Sharpe: {sharpe:.2f} | Max DD: {max_dd:.1%} | WFE: {wfe_str}
Status: {status}
File: composite_{args.symbol}_{args.interval}_{args.start}_{args.end}.json
"""
    try:
        with open(summary_path, "a") as f:
            f.write(entry)
        logger.info(f"SUMMARY.md updated at {summary_path}")
    except Exception as e:
        logger.warning(f"Could not update SUMMARY.md: {e}")


if __name__ == "__main__":
    main()
