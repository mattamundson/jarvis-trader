"""Regime decomposition validator — Tier A P4 / A7.

Retro-buckets a strategy's trade list by market regime at entry, using:

  * `RegimeClassifier.classify()` → TRENDING / RANGING / VOLATILE per bar
  * `compute_adx()` → ADX bucket (weak <20, mid 20-25, strong >25)

This is a pure retrospective analysis — no strategy modification. The
output answers: "does the edge concentrate in one regime, or is it
diversified?" A strategy with PF 2.5 in TRENDING but PF 0.6 in RANGING
is actually a fragile edge that depends on the current market structure
persisting. A strategy with PF 1.5 across all three regimes is more
robust.

Usage (from engine/):
    .venv/Scripts/python -u -m scripts.regime_decomposition \\
        --results-file scripts/mes_trend_search_results.json \\
        --rank 7 --symbol MES

Output: per-regime PF, Sharpe, win rate, trade count, per-bucket ADX
distribution. Flags regime-conditional failures.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.indicators import compute_adx  # noqa: E402
from backtest.regime import RegimeClassifier  # noqa: E402

ADX_BUCKETS = [("weak (<20)", 0, 20), ("mid (20-25)", 20, 25), ("strong (>=25)", 25, 1000)]


def _pf_from_pnls(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p <= 0))
    if losses == 0:
        return 999.0 if wins > 0 else 0.0
    return wins / losses


def _sharpe_from_pnls(pnls: list[float], ann_factor: float = 252.0) -> float:
    if len(pnls) < 2:
        return 0.0
    arr = np.asarray(pnls, dtype=float)
    mean = arr.mean()
    std = arr.std(ddof=1)
    if std == 0:
        return 0.0
    return float(mean / std * np.sqrt(ann_factor))


def _bucket_stats(trades: list[dict], initial_capital: float = 10_000.0) -> dict:
    """Compute PF/Sharpe/WR for a list of trade dicts."""
    if not trades:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "sharpe": 0.0,
                "net_pnl": 0.0, "avg_pnl": 0.0, "ret_pct": 0.0}
    pnls = [float(t["pnl"]) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    net = sum(pnls)
    return {
        "n": len(trades),
        "pf": round(_pf_from_pnls(pnls), 3),
        "wr": round(wins / len(pnls) * 100, 1),
        "sharpe": round(_sharpe_from_pnls(pnls), 3),
        "net_pnl": round(net, 2),
        "avg_pnl": round(net / len(trades), 2),
        "ret_pct": round(net / initial_capital * 100, 2),
    }


def _load_trades_from_results(results_file: Path, rank: int) -> dict:
    with open(results_file) as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    entry = results[rank - 1]
    if "trades" not in entry or not entry["trades"]:
        raise ValueError("trades field missing/empty — regenerate results file (A2 emission)")
    return {
        "symbol": doc.get("symbol", "UNKNOWN"),
        "interval": doc.get("interval", "1h"),
        "start": doc.get("start"),
        "end": doc.get("end"),
        "params": entry.get("params"),
        "trades": entry["trades"],
    }


def _adx_bucket(adx_value: float) -> str:
    for label, lo, hi in ADX_BUCKETS:
        if lo <= adx_value < hi:
            return label
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description="Regime decomposition validator (Tier A P4)")
    ap.add_argument("--results-file", required=True)
    ap.add_argument("--rank", type=int, default=1)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    results_file = Path(args.results_file).resolve()
    loaded = _load_trades_from_results(results_file, args.rank)
    symbol = args.symbol.upper()

    print(f"Regime decomposition: {symbol} rank={args.rank}", flush=True)
    print(f"  params={loaded['params']}", flush=True)
    print(f"  trades={len(loaded['trades'])}", flush=True)

    t0 = time.time()
    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data for {symbol}", flush=True)
        return 1

    # Classify every bar; compute ADX on same grid
    classifier = RegimeClassifier()
    df = classifier.classify(df)
    adx_df = compute_adx(df, period=14)
    df["adx"] = adx_df["adx"]

    # Tag each trade with regime + ADX at entry
    tagged_trades = []
    unmatched = 0
    for t in loaded["trades"]:
        entry_time = pd.Timestamp(t["entry_time"])
        # Find the nearest bar at-or-before entry_time
        try:
            idx_pos = df.index.get_indexer([entry_time], method="pad")[0]
            if idx_pos < 0:
                unmatched += 1
                continue
            bar = df.iloc[idx_pos]
            regime = bar["regime_type"] if not pd.isna(bar.get("regime_type", None)) else "UNKNOWN"
            adx_v = float(bar["adx"]) if not pd.isna(bar["adx"]) else np.nan
            tagged_trades.append({
                **t,
                "regime_at_entry": regime,
                "adx_at_entry": round(adx_v, 2) if not pd.isna(adx_v) else None,
                "adx_bucket": _adx_bucket(adx_v) if not pd.isna(adx_v) else "unknown",
            })
        except Exception:
            unmatched += 1

    if unmatched:
        print(f"  WARNING: {unmatched} trades could not be matched to OHLCV bars", flush=True)

    # Bucket by regime_type
    print("\n=== Decomposition by RegimeClassifier label ===", flush=True)
    print(f"{'regime':>12}  {'n':>4}  {'PF':>6}  {'WR%':>5}  {'Sharpe':>7}  {'avg_pnl':>8}  {'ret%':>7}", flush=True)
    regime_stats = {}
    for regime in ["TRENDING", "RANGING", "VOLATILE", "UNKNOWN"]:
        bucket = [t for t in tagged_trades if t.get("regime_at_entry") == regime]
        if not bucket:
            continue
        s = _bucket_stats(bucket)
        regime_stats[regime] = s
        print(f"{regime:>12}  {s['n']:>4}  {s['pf']:>6.2f}  {s['wr']:>5.1f}  "
              f"{s['sharpe']:>7.2f}  ${s['avg_pnl']:>7.2f}  {s['ret_pct']:>+7.2f}", flush=True)

    # Bucket by ADX strength
    print("\n=== Decomposition by ADX strength ===", flush=True)
    print(f"{'adx_bucket':>15}  {'n':>4}  {'PF':>6}  {'WR%':>5}  {'Sharpe':>7}  {'avg_pnl':>8}  {'ret%':>7}", flush=True)
    adx_stats = {}
    for label, _lo, _hi in ADX_BUCKETS:
        bucket = [t for t in tagged_trades if t.get("adx_bucket") == label]
        if not bucket:
            continue
        s = _bucket_stats(bucket)
        adx_stats[label] = s
        print(f"{label:>15}  {s['n']:>4}  {s['pf']:>6.2f}  {s['wr']:>5.1f}  "
              f"{s['sharpe']:>7.2f}  ${s['avg_pnl']:>7.2f}  {s['ret_pct']:>+7.2f}", flush=True)

    # Conditional failure flag: PF < 1.0 in any bucket with >=20% of sample
    sample_n = len(tagged_trades) if tagged_trades else 1
    flags = []
    for name, buckets in [("regime", regime_stats), ("adx", adx_stats)]:
        for key, stats in buckets.items():
            if stats["n"] >= max(3, 0.2 * sample_n) and stats["pf"] < 1.0:
                flags.append(f"{name}:{key} unprofitable (PF {stats['pf']:.2f}, n={stats['n']}, "
                             f"{stats['n']/sample_n*100:.0f}% of trades)")

    # Regime concentration flag: any single regime has >70% of trades
    concentrations = []
    for regime, stats in regime_stats.items():
        pct = stats["n"] / sample_n * 100
        if pct > 70:
            concentrations.append(f"{regime} ({pct:.0f}%)")

    print("\n=== Summary ===", flush=True)
    if flags:
        print("CONDITIONAL FAILURES:", flush=True)
        for f in flags:
            print(f"  - {f}", flush=True)
    else:
        print("No conditional failures detected (all material buckets PF >= 1.0).", flush=True)

    if concentrations:
        print(f"REGIME CONCENTRATION: {', '.join(concentrations)}", flush=True)
        print("  → Edge depends on current regime persisting. If regime shifts, edge may evaporate.", flush=True)
    else:
        print("No severe regime concentration (no regime > 70% of trades).", flush=True)

    out_path = _ENGINE / "scripts" / "validation_reports" / \
               f"{symbol}_rank{args.rank}_regime_decomposition.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol, "rank": args.rank,
            "params": loaded["params"],
            "n_trades": len(tagged_trades),
            "n_unmatched": unmatched,
            "regime_stats": regime_stats,
            "adx_stats": adx_stats,
            "conditional_failures": flags,
            "regime_concentrations": concentrations,
            "tagged_trades": tagged_trades,
            "elapsed_sec": round(time.time() - t0, 1),
        }, f, indent=2, default=str)
    print(f"\nSaved to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
