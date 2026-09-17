#!/usr/bin/env python
"""MES VIX-percentile champion — economics and DSR-trial-count sensitivity.

Purpose
-------
The gate-v2 verdict for `MES_sma_trend_vix_pctile_blockCrisis_v1`
(`engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json`, 2026-09-17) reports
PASS via alt with `p_edge=0.5926`, `dsr=0.9752`, and champion `blocked_tiers=[]`.
Two things that verdict does NOT establish, and that this script measures:

1. **Economic significance.** Gate v2 records PF / DD / Sharpe per window but no CAGR.
   PF/Sharpe alone hide economic triviality — the certified live champion
   SMA(50,200)+2xATR is -0.26% CAGR over 7.27y at fixed params. This script reports
   CAGR from the actual equity curve.
2. **DSR sensitivity to the trial count.** `trade_level_dsr` is deflated for the
   *runner's own grid size* (`n_grid_combos=4`). The true MES-campaign trial count
   against this deep cache is in the hundreds, and DSR is a cliff. This script
   recomputes the same DSR at several trial counts to show where the PASS collapses.

Parity discipline: the WFO replay must reproduce the archived verdict's numbers
(`p_edge`, total OOS trades, `dsr` at the runner's own grid size) before any of its
own output is trusted. `--expect-*` flags assert that.

Research only. Writes nothing to `engine/data/gate_v2_verdicts/`. No live/paper
routing, risk, kill-switch, broker, or `.env` surface is touched.

Usage (from `engine/`):
    env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' \
      .venv/Scripts/python.exe backtest/analyze_mes_vix_pctile_economics.py --out ../docs/research/x.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest._gate_v2_helpers import bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_trade_metrics import trade_level_dsr  # noqa: E402
from backtest.metrics import calculate_metrics  # noqa: E402
from backtest.run_mes_trend_vix_pctile_rank1 import (  # noqa: E402
    CAPITAL,
    FAST,
    MIN_OOS_TRADES_PER_WINDOW,
    SLOW,
    TIER_BLOCK_GRID,
    VIX_REGIME_LOOKBACK,
    _best_is_block,
    _generate_windows,
    _label,
    _load_mes_data,
    _load_vix_data,
    _run_signals_and_backtest,
)

#: Trial counts to deflate DSR against. 4 is the runner's own grid size; the rest
#: bracket the plausible real MES-campaign trial count against the deep cache.
TRIAL_COUNTS = (4, 9, 25, 50, 100, 200, 500)

#: Sign-permutation count for the empirical DSR null. Lower than the gate default
#: (10,000) purely to bound wall-clock on a sensitivity sweep.
DSR_PERMUTATIONS = 2000

DEEP_CACHE_HINT = "MES_2019-05-05_2026-08-26_1h.csv"


def _cache_facts(path: Path) -> dict:
    raw = path.read_bytes()
    ts = pd.read_csv(path)["timestamp"]
    ts = pd.to_datetime(ts, utc=True, errors="coerce")
    return {
        "file": path.name,
        "rows": int(len(ts)),
        "span": [str(ts.min()), str(ts.max())],
        "nan_timestamps": int(ts.isna().sum()),
        "duplicate_timestamps": int(ts.duplicated().sum()),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _p_edge(oos_results: list) -> float:
    """Mirror the runner's p_edge exactly.

    The runner uses ``oos_pfs = [r.profit_factor for r in oos_results
    if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]`` then counts ``pf > 1.0``.
    ``inf`` (a single winning trade) therefore COUNTS as > 1.0 — filtering
    non-finite values out silently deflates the metric, which is exactly the
    parity bug this helper had on its first run (0.12 vs the true 0.5926).
    """
    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    if not oos_pfs:
        return 0.0
    return round(float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs))), 4)


def _replay_wfo(df: pd.DataFrame, vix_df: pd.DataFrame) -> tuple[list, list]:
    """Reproduce the runner's walk-forward loop exactly (see run_mes_trend_vix_pctile_rank1)."""
    windows = _generate_windows(df)
    oos_results, records = [], []
    for win in windows:
        df_train = df[(df.index >= win["train_start"]) & (df.index < win["train_end"])]
        df_test = df[(df.index >= win["test_start"]) & (df.index <= win["test_end"])]
        best_block, is_result = _best_is_block(df_train, vix_df, TIER_BLOCK_GRID)
        if best_block is None:
            continue
        try:
            oos = _run_signals_and_backtest(df_test, vix_df, best_block)
        except Exception as exc:  # pragma: no cover - mirrors runner behaviour
            print(f"  [SKIP] OOS error w{win['window_num']}: {exc}")
            continue
        oos_results.append(oos)
        records.append({"window": win["window_num"], "best_blocked_tiers": list(best_block),
                        "is_pf": round(is_result.profit_factor, 3), "oos_pf": round(oos.profit_factor, 3),
                        "oos_trades": oos.total_trades})
    return oos_results, records


def _full_sample_economics(df: pd.DataFrame, vix_df: pd.DataFrame, block: tuple[str, ...]) -> dict:
    """Fixed-params run over the whole sample -> CAGR, DD, honest Sharpe, trade frequency."""
    result = _run_signals_and_backtest(df, vix_df, block)
    calculate_metrics(result)

    equity = list(result.equity_curve)
    years = (result.trades[-1].exit_date - result.trades[0].entry_date).days / 365.25 if result.trades else 0.0
    span_years = (df.index.max() - df.index.min()).days / 365.25
    final = float(equity[-1]) if equity else float(CAPITAL)
    cagr = ((final / CAPITAL) ** (1 / span_years) - 1) * 100 if span_years > 0 else float("nan")

    n_trades = result.total_trades
    tpy = n_trades / span_years if span_years > 0 else float("nan")
    engine_sharpe = float(result.sharpe_ratio)
    # Honest Sharpe deflates the engine annualisation (which assumes 252 trades/yr)
    # to the OBSERVED trade frequency. See skills/strategy-validation-integrity.
    honest = engine_sharpe * math.sqrt(tpy / 252) if tpy and tpy > 0 else 0.0

    trades = result.trades
    pnls = np.array([t.pnl for t in trades], dtype=float)
    return {
        "blocked_tiers": list(block),
        "label": _label(block),
        "trades": n_trades,
        "trades_per_year": round(tpy, 3),
        "span_years": round(span_years, 3),
        "trade_window_years": round(years, 3),
        "profit_factor": round(float(result.profit_factor), 4),
        "win_rate_pct": round(100 * float(result.win_rate), 2) if hasattr(result, "win_rate") else None,
        "total_pnl": round(float(pnls.sum()), 2) if pnls.size else 0.0,
        "final_equity": round(final, 2),
        "cagr_pct": round(cagr, 4) if math.isfinite(cagr) else None,
        "max_drawdown_pct": round(float(result.max_drawdown_pct) * 100, 4),
        "engine_sharpe": round(engine_sharpe, 4),
        "honest_sharpe_observed_tpy": round(honest, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None, help="write the JSON result here")
    ap.add_argument("--cache", default=DEEP_CACHE_HINT, help="cache filename inside backtest/cache")
    ap.add_argument("--expect-p-edge", type=float, default=0.5926)
    ap.add_argument("--expect-trades", type=int, default=63)
    ap.add_argument("--expect-dsr-grid", type=float, default=0.9752, help="dsr at the runner's n_combos")
    ap.add_argument("--dsr-tolerance", type=float, default=0.02)
    args = ap.parse_args()

    data_dir = engine_root / "backtest" / "cache"
    cache_path = data_dir / args.cache
    if not cache_path.exists():
        print(f"[ECON] ERROR: cache not found: {cache_path}")
        return 2
    facts = _cache_facts(cache_path)
    print(f"[ECON] cache {facts['file']} rows={facts['rows']} span={facts['span'][0]}..{facts['span'][1]}")

    df = _load_mes_data(data_dir)
    vix_df = _load_vix_data(start=str(df.index.min().date()))

    oos_results, records = _replay_wfo(df, vix_df)
    if not oos_results:
        print("[ECON] ERROR: replay produced no OOS results")
        return 3

    p_edge = _p_edge(oos_results)
    total_oos_trades = int(sum(r.total_trades for r in oos_results))
    windows_with_trades = int(sum(1 for r in oos_results if r.total_trades > 0))

    dsr_by_trials = {}
    for n in TRIAL_COUNTS:
        dsr_by_trials[n] = round(
            float(trade_level_dsr(oos_results, n_grid_combos=n, initial_capital=CAPITAL,
                                  n_permutations=DSR_PERMUTATIONS)), 6)
        print(f"[ECON] dsr(n_trials={n:>4}) = {dsr_by_trials[n]:.6f}")

    dsr_grid = dsr_by_trials.get(4, float("nan"))
    parity = {
        "p_edge_replay": p_edge, "p_edge_expected": args.expect_p_edge,
        "trades_replay": total_oos_trades, "trades_expected": args.expect_trades,
        "dsr_grid_replay": dsr_grid, "dsr_grid_expected": args.expect_dsr_grid,
        "tolerance": args.dsr_tolerance,
        "p_edge_match": abs(p_edge - args.expect_p_edge) < 1e-9,
        "trades_match": total_oos_trades == args.expect_trades,
        "dsr_match": abs(dsr_grid - args.expect_dsr_grid) <= args.dsr_tolerance,
    }
    parity["ok"] = bool(parity["p_edge_match"] and parity["trades_match"] and parity["dsr_match"])
    print(f"[ECON] parity vs archived verdict: {json.dumps(parity)}")
    if not parity["ok"]:
        print("[ECON] PARITY FAILED - downstream numbers are not comparable to the verdict")

    champion_block: tuple[str, ...] = ()
    econ = [
        _full_sample_economics(df, vix_df, champion_block),
        _full_sample_economics(df, vix_df, ("Crisis",)),
    ]
    for row in econ:
        print(f"[ECON] full-sample block=[{row['label']:>8}] PF={row['profit_factor']} "
              f"CAGR={row['cagr_pct']}% DD={row['max_drawdown_pct']}% "
              f"trades={row['trades']} tpy={row['trades_per_year']} "
              f"engine_sharpe={row['engine_sharpe']} honest={row['honest_sharpe_observed_tpy']}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "MES",
        "candidate_id": "MES_sma_trend_vix_pctile_blockCrisis_v1",
        "sma_params": {"fast": FAST, "slow": SLOW, "atr_trail_mult": 2.0},
        "vix_regime_lookback": VIX_REGIME_LOOKBACK,
        "cache": facts,
        "wfo_replay": {"n_windows": len(records), "n_windows_with_trades": windows_with_trades,
                       "total_oos_trades": total_oos_trades, "p_edge": p_edge,
                       "oos_window_pfs": [round(float(r.profit_factor), 4) if math.isfinite(r.profit_factor)
                                          else str(r.profit_factor) for r in oos_results],
                       "champion_blocked_tiers": "[] (no gate) per window-IS selection"},
        "dsr_by_trial_count": {str(k): v for k, v in dsr_by_trials.items()},
        "dsr_permutations": DSR_PERMUTATIONS,
        "parity_vs_archived_verdict": parity,
        "full_sample_economics": econ,
        "pf_ci_lower_full_sample": {
            "champion": round(float(bootstrap_pf_ci_lower([r.profit_factor for r in oos_results
                                                            if r.total_trades > 0])), 4),
            "note": "OOS-window PF bootstrap, mirrors the gate's pf_ci_lower input",
        },
        "research_only": True,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"[ECON] wrote {args.out.as_posix()}")

    return 0 if parity["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
