"""Fixed-params temporal validator — Tier A follow-up P3.

Distinct question from rolling_wfo_validator:

    rolling_wfo_validator asks "if we re-run grid search in each window,
    does A winner emerge on every out-of-sample test?"

    fixed_params_temporal_validator asks "do THESE specific params work
    across N independent temporal segments, without reoptimization?"

The former can overfit on 15-25-trade train windows for sparse strategies
(trivial train PF of infinity collapses on OOS). The latter is the
anti-overfitting lens: you commit to one config and ask whether it holds
up across non-overlapping time slices.

Source insight: 2026-04-21 03:38 CT rule from Phase B stress test
(`a9358ce`). Rolling grid-search WFO failed MES SMA; fixed-params temporal
validation of the live champion (50, 200, 2.0) across 4 independent 6-month
segments produced PF 1.69 / 2.10 / 1.77 / 1.21 — all profitable.

Usage (from engine/):
    .venv/Scripts/python -u -m scripts.fixed_params_temporal_validator \\
        --symbol MES --family trend --params '{"fast":50,"slow":200,"atr_trail_mult":2.0}' \\
        --n-segments 4

    .venv/Scripts/python -u -m scripts.fixed_params_temporal_validator \\
        --symbol MES --family trend --rank 7  # pull params from grid results

Verdict bands:
    STRONG    — all segments profitable AND min PF >= 1.30
    MODERATE  — all segments profitable AND min PF >= 1.00
    MIXED     — >= 70% of segments profitable
    FAIL      — otherwise
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

from backtest.contract_specs import get_spec  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402


def _spec_dict(symbol: str) -> dict:
    s = get_spec(symbol)
    return {
        "multiplier": s.multiplier,
        "tick_size": s.tick_size,
        "commission": s.commission,
        "slippage_ticks": s.slippage_ticks,
    }


def _load_params_from_rank(results_file: Path, rank: int) -> dict:
    with open(results_file) as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    return results[rank - 1].get("params", {})


def _split_into_segments(df: pd.DataFrame, n_segments: int) -> list[pd.DataFrame]:
    """Split a time-indexed DataFrame into N equal-length non-overlapping segments."""
    n = len(df)
    segment_len = n // n_segments
    segments = []
    for i in range(n_segments):
        start = i * segment_len
        end = (i + 1) * segment_len if i < n_segments - 1 else n
        segments.append(df.iloc[start:end])
    return segments


def _verdict(segment_pfs: list[float], all_profitable: bool) -> str:
    if not segment_pfs:
        return "FAIL"
    # Filter out 999 sentinels (no-loss is not an honest PF)
    finite = [pf for pf in segment_pfs if 0 < pf < 900]
    pct_profitable = sum(1 for pf in segment_pfs if pf >= 1.0) / len(segment_pfs)
    min_pf = min(finite) if finite else 0.0

    if all_profitable and min_pf >= 1.30:
        return "STRONG"
    if all_profitable and min_pf >= 1.00:
        return "MODERATE"
    if pct_profitable >= 0.70:
        return "MIXED"
    return "FAIL"


def main():
    ap = argparse.ArgumentParser(description="Fixed-params temporal validator (P3)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--family", required=True,
                    choices=["trend", "meanrev", "breakout", "meanrev_regime",
                             "composite", "saty", "tpo"])
    ap.add_argument("--params", default=None,
                    help='JSON dict of strategy params. If omitted, use --rank from results file.')
    ap.add_argument("--rank", type=int, default=None,
                    help="Pull params from rank-th entry in --results-file")
    ap.add_argument("--results-file", default=None,
                    help="Override auto-detected results file for --rank lookup")
    ap.add_argument("--n-segments", type=int, default=4,
                    help="Number of independent temporal segments (default 4)")
    ap.add_argument("--min-trades-per-segment", type=int, default=10,
                    help="Flag segments with fewer trades as 'thin' and down-weight "
                         "them in the verdict. A 6-trade PF is essentially noise.")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    symbol = args.symbol.upper()

    # Dispatch to research harness
    if args.family == "trend":
        from scripts.mes_trend_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_trend_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["fast"], params["slow"],
                                params["atr_trail_mult"], spec)
    elif args.family == "meanrev":
        from scripts.mcl_meanrev_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_meanrev_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["bb_period"], params["bb_std"],
                                params["atr_stop_mult"], params["max_hold_bars"], spec)
    elif args.family == "breakout":
        from scripts.mnq_breakout_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_breakout_search_results.json"
        def runner(df, params, spec):
            return _run_harness(
                df,
                donchian_period=params["donchian_period"],
                vol_ma_period=params.get("vol_ma_period", 20),
                vol_mult=params.get("vol_mult", 1.0),
                stop_atr_mult=params.get("stop_atr_mult", 2.0),
                short_only=params.get("short_only", True),
                spec=spec,
            )
    elif args.family == "composite":
        from scripts.mes_composite_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_composite_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["entry_threshold"], params["band_mult"], spec, symbol)
    elif args.family == "saty":
        from scripts.mes_saty_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_saty_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["target_ratio"], spec, symbol)
    elif args.family == "tpo":
        from scripts.mes_tpo_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_tpo_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["enter"], params["stop_mult"], spec, symbol)
    else:  # meanrev_regime — Bollinger+RSI w/ regime filter (MCL bbwidth variant)
        from scripts.mcl_meanrev_regime_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / \
            f"{symbol.lower()}_meanrev_regime_search_results.json"
        def runner(df, params, spec):
            return _run_harness(
                df,
                bb_period=params["bb_period"],
                bb_std=params["bb_std"],
                rsi_long=params.get("rsi_long", 30.0),
                rsi_short=params.get("rsi_short", 70.0),
                stop_atr_mult=params["stop_atr_mult"],
                regime_filter_mode=params.get("regime_filter_mode", "bbwidth"),
                regime_filter_bbwidth_pct=params.get("regime_filter_bbwidth_pct", 40.0),
                regime_filter_adx_threshold=params.get("regime_filter_adx_threshold", 20.0),
                spec=spec,
            )

    # Resolve params
    if args.params:
        params = json.loads(args.params)
    elif args.rank is not None:
        rf = Path(args.results_file) if args.results_file else default_rf
        params = _load_params_from_rank(rf, args.rank)
    else:
        print("[ERROR] must provide --params or --rank", flush=True)
        return 1

    spec = _spec_dict(symbol)
    print(f"Fixed-params temporal validation: {symbol} {args.family}", flush=True)
    print(f"  params={params}", flush=True)
    print(f"  segments={args.n_segments}, range={args.start} -> {args.end}", flush=True)

    t0 = time.time()
    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data for {symbol}", flush=True)
        return 1

    segments = _split_into_segments(df, args.n_segments)
    segment_results = []
    thin_segments = []  # for visibility — segments below the trade-count floor
    for i, seg in enumerate(segments, 1):
        if len(seg) < 50:
            continue
        r = runner(seg, params, spec)
        if r.get("skipped"):
            continue
        entry = {
            "segment": i,
            "start": str(seg.index.min())[:10],
            "end": str(seg.index.max())[:10],
            "n_bars": len(seg),
            "pf": r["pf"],
            "wr": r["wr"],
            "total_trades": r["total_trades"],
            "net_pnl": r["net_pnl"],
            "ret_pct": r["ret_pct"],
            "thin": r["total_trades"] < args.min_trades_per_segment,
        }
        segment_results.append(entry)
        if entry["thin"]:
            thin_segments.append(entry)

    if not segment_results:
        print("[ERROR] No segments produced valid results", flush=True)
        return 1

    segment_pfs = [s["pf"] for s in segment_results]
    total_trades = sum(s["total_trades"] for s in segment_results)
    all_profitable = all(s["pf"] >= 1.0 for s in segment_results)
    profitable = sum(1 for s in segment_results if s["pf"] >= 1.0)

    finite = [pf for pf in segment_pfs if 0 < pf < 900]
    min_pf = min(finite) if finite else 0.0
    max_pf = max(finite) if finite else 0.0
    mean_pf = float(np.mean(finite)) if finite else 0.0

    verdict = _verdict(segment_pfs, all_profitable)

    # Report
    print(f"\n{'seg':>3} {'start':>10}-{'':10} {'bars':>5} {'PF':>6} {'WR%':>5} {'n':>4} {'ret%':>7}", flush=True)
    for s in segment_results:
        print(f"{s['segment']:>3} {s['start']}-{s['end']} "
              f"{s['n_bars']:>5} {s['pf']:>6.2f} {s['wr']:>5.1f} "
              f"{s['total_trades']:>4} {s['ret_pct']:>+7.2f}", flush=True)

    print(f"\nSegment PFs: {[round(pf, 3) for pf in segment_pfs]}", flush=True)
    print(f"  min={min_pf:.3f} max={max_pf:.3f} mean={mean_pf:.3f}", flush=True)
    print(f"  profitable: {profitable}/{len(segment_results)} segments "
          f"(all_profitable={all_profitable})", flush=True)
    print(f"  total trades across segments: {total_trades}", flush=True)
    if thin_segments:
        print(f"  WARNING: {len(thin_segments)} segment(s) below "
              f"{args.min_trades_per_segment}-trade floor — "
              f"their PF is noise-dominated", flush=True)
        for ts in thin_segments:
            print(f"    seg {ts['segment']}: only {ts['total_trades']} trades", flush=True)
    print(f"\nTemporal-stability verdict: {verdict}", flush=True)
    if thin_segments and verdict in ("MIXED", "FAIL"):
        thick_pfs = [s["pf"] for s in segment_results if not s["thin"]]
        thick_profitable = all(pf >= 1.0 for pf in thick_pfs) if thick_pfs else False
        thick_min = min(thick_pfs) if thick_pfs else 0
        print(f"\nExcluding thin segments: {len(thick_pfs)} thick segments, "
              f"all profitable={thick_profitable}, min_pf={thick_min:.3f}", flush=True)

    # Filename tag based on symbol+family only (params recorded in JSON body)
    out_path = _ENGINE / "scripts" / "validation_reports" / \
               f"{symbol}_{args.family}_fixed_params_temporal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol, "family": args.family, "params": params,
            "n_segments": args.n_segments,
            "start": args.start, "end": args.end,
            "segments": segment_results,
            "segment_pfs": segment_pfs,
            "stats": {
                "min_pf": round(min_pf, 3),
                "max_pf": round(max_pf, 3),
                "mean_pf": round(mean_pf, 3),
                "all_profitable": all_profitable,
                "pct_profitable": round(profitable / len(segment_results), 3),
                "total_trades": total_trades,
            },
            "verdict": verdict,
            "elapsed_sec": round(time.time() - t0, 1),
        }, f, indent=2)
    print(f"\nSaved to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
