#!/usr/bin/env python
"""
MNQ Breakout Gate v2 — Rank 7 ATR+EMA Regime Filter (Expanded Grid)

Root cause from rank 6: atr_regime_mult=[1.0, 1.2] was too strict — it required
ATR to already be at/above its 50-bar SMA, which cut signal count so aggressively
in the mid-2025 chop windows that p_edge collapsed to 0.0 (0 of 18 OOS windows
profitable). The regime filter hypothesis is still valid; calibration was wrong.

Rank 7 hypothesis:
  1. Lower ATR gate floor: [0.5, 0.75] allows moderate-expansion environments
  2. Include ema_trend_period=0 (disabled) as baseline control
  3. Widen donchian to [20, 30] — less noise-sensitive breakout definition
  4. Promote vol_mult to grid [0.8, 1.0] — sub-1.0 not yet tested
  5. Fix stop_atr_mult=2.0 (rank 1-6 consensus)

Grid: atr_regime_mult=[0.5, 0.75, 1.0, 1.25]
    x ema_trend_period=[0, 50, 100, 200]
    x donchian_period=[20, 30]
    x vol_mult=[0.8, 1.0]
= 64 combos

Rank 6 result (FAIL):
    pf_ci_lower=0.4076  p_edge=0.0000  mc_95th_dd=1.84%  dsr=0.0000
    Root cause: atr_regime_mult>=1.0 gated too aggressively

Gate v2 thresholds:
    pf_ci_lower >= 1.10 | p_edge >= 0.95 | mc_95th_dd <= 5% | dsr >= 0.10

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mnq_breakout_rank7.py
"""
from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

SYMBOL = "MNQ"
MULTIPLIER = 2.0
CAPITAL = 25_000.0
TICK_SIZE = 0.25
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

ATR_REGIME_MULT_VALUES = [0.5, 0.75, 1.0, 1.25]
EMA_TREND_PERIOD_VALUES = [0, 50, 100, 200]
DONCHIAN_PERIOD_VALUES = [20, 30]
VOL_MULT_VALUES = [0.8, 1.0]
STOP_ATR_MULT = 2.0
VOL_MA_PERIOD = 20

GATE_WFO_CONSISTENCY = ["MODERATE", "STRONG"]

MIN_OOS_TRADES = 5


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    return df.set_index(ts_col).sort_index()


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    start, end = df.index.min(), df.index.max()
    windows, cursor, n = [], start, 1
    while True:
        te = cursor + pd.DateOffset(months=TRAIN_MONTHS)
        os_ = te
        oe = os_ + pd.DateOffset(months=TEST_MONTHS)
        if os_ >= end:
            break
        if oe > end:
            oe = end
        tr = df[(df.index >= cursor) & (df.index < te)]
        te_ = df[(df.index >= os_) & (df.index <= oe)]
        if len(tr) >= 30 and len(te_) >= 30:
            windows.append(
                {
                    "num": n,
                    "ts": cursor,
                    "te": te,
                    "os": os_,
                    "oe": oe,
                    "n_train": len(tr),
                    "n_test": len(te_),
                }
            )
            n += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= end:
            break
    return windows


def _run(df: pd.DataFrame, donchian_period, ema_trend_period, atr_regime_mult, vol_mult):
    from backtest.backtester import Backtester
    from backtest.breakout_signals import generate_donchian_breakout_signals

    sig = generate_donchian_breakout_signals(
        df,
        donchian_period=donchian_period,
        vol_ma_period=VOL_MA_PERIOD,
        vol_mult=vol_mult,
        stop_atr_mult=STOP_ATR_MULT,
        ema_trend_period=ema_trend_period,
        atr_regime_mult=atr_regime_mult,
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _best_is(df_train, grid):
    best_pf, best_p, best_r = -1.0, None, None
    for p in grid:
        try:
            r = _run(df_train, *p)
        except Exception as e:
            print(f"    [WARN] IS {p}: {e}")
            continue
        if r.total_trades < MIN_OOS_TRADES and r.profit_factor > best_pf:
            continue
        if r.profit_factor > best_pf:
            best_pf, best_p, best_r = r.profit_factor, p, r
    return best_p, best_r


from backtest._constants import (  # noqa: E402
    GATE_FIXED_PARAMS_MIN_PF,
)
from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf  # noqa: E402


def _gate_v2(oos_results, n_combos, fixed_metrics):
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES]
    dds = [r.max_drawdown_pct for r in oos_results]
    tot = sum(r.total_trades for r in oos_results)

    pf_ci = _bootstrap_pf(pfs)
    p_edge = float(sum(1 for p in pfs if p > 1.0) / max(1, len(pfs)))
    mc_dd = float(np.percentile(dds, 95.0)) if dds else 1.0
    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (a 1-2 trade window's giant Sharpe deflated to a fake ~1.0 and
    # auto-passed both gate floors). See _gate_v2_trade_metrics for the why.
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_combos, initial_capital=CAPITAL)
    wfo = (
        "STRONG"
        if sum(1 for p in pfs if p > 1.0) / max(1, len(pfs)) >= 0.75
        else "MODERATE" if sum(1 for p in pfs if p > 1.0) / max(1, len(pfs)) >= 0.55 else "WEAK"
    )
    fpm = fixed_metrics.get("fixed_params_min_pf", 0.0)

    core = (
        pf_ci >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt = (
        pf_ci >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_dd <= GATE_MC_DD_ALT
        and dsr >= GATE_DSR
        and fpm >= GATE_FIXED_PARAMS_MIN_PF
        and wfo in GATE_WFO_CONSISTENCY
    )
    return {
        "pf_ci_lower": round(pf_ci, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_dd, 6),
        "dsr": round(dsr, 4),
        "wfo_consistency": wfo,
        "fixed_params_min_pf": fpm,
        "fixed_params_mean_pf": fixed_metrics.get("fixed_params_mean_pf", 0.0),
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(pfs),
        "total_oos_trades": tot,
        "core_verdict": "PASS" if core else "FAIL",
        "alt_verdict": "PASS" if alt else "FAIL",
        "verdict": "PASS" if core else ("PASS_ALT" if alt else "FAIL"),
    }


def run_wfo():
    # Pick the MNQ 1h cache covering the latest end-date so a refreshed
    # IBKR pull (named MNQ_<start>_<end>_1h.csv) always wins over older files.
    cache_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(cache_dir, "MNQ")
    print(f"[MNQ-R7] Selected {data_file.name}")

    print(f"[MNQ-R7] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MNQ-R7] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    grid = list(
        itertools.product(
            DONCHIAN_PERIOD_VALUES, EMA_TREND_PERIOD_VALUES, ATR_REGIME_MULT_VALUES, VOL_MULT_VALUES
        )
    )
    n_combos = len(grid)

    print(f"\n{'='*65}")
    print("=== MNQ BREAKOUT RANK 7 - ATR+EMA REGIME FILTER ===")
    print(f"Windows: {len(windows)} | Grid: {n_combos} combos")
    print(f"  donchian  : {DONCHIAN_PERIOD_VALUES}")
    print(f"  ema_period: {EMA_TREND_PERIOD_VALUES}  (0=disabled baseline)")
    print(f"  atr_mult  : {ATR_REGIME_MULT_VALUES}  (rank6: [1.0,1.2] -> p_edge=0.0)")
    print(f"  vol_mult  : {VOL_MULT_VALUES}")
    print(f"{'='*65}")

    oos_results, win_records = [], []
    for win in windows:
        n, ts, te, os_, oe = win["num"], win["ts"], win["te"], win["os"], win["oe"]
        print(
            f"\nWindow {n}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  "
            f"({win['n_train']}/{win['n_test']} bars)"
        )

        df_tr = df[(df.index >= ts) & (df.index < te)].copy()
        df_te = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_p, is_r = _best_is(df_tr, grid)
        if best_p is None:
            print("  [SKIP] No valid IS params")
            continue
        don, ema, atr_m, vm = best_p
        print(
            f"  Best IS: don={don} ema={ema} atr_m={atr_m} vol={vm}  "
            f"PF={is_r.profit_factor:.2f} trades={is_r.total_trades}"
        )

        try:
            oos_r = _run(df_te, don, ema, atr_m, vm)
        except Exception as e:
            print(f"  [SKIP] OOS error: {e}")
            continue

        print(
            f"  OOS: PF={oos_r.profit_factor:.2f}  DD={oos_r.max_drawdown_pct:.1%}  "
            f"Sharpe={oos_r.sharpe_ratio:.2f}  trades={oos_r.total_trades}"
        )
        oos_results.append(oos_r)
        win_records.append(
            {
                "window": n,
                "is_period": f"{ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}",
                "best_params": {
                    "donchian_period": don,
                    "ema_trend_period": ema,
                    "atr_regime_mult": atr_m,
                    "vol_mult": vm,
                    "stop_atr_mult": STOP_ATR_MULT,
                },
                "is_pf": round(is_r.profit_factor, 3),
                "is_trades": is_r.total_trades,
                "oos_pf": round(oos_r.profit_factor, 3),
                "oos_dd": round(oos_r.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_r.sharpe_ratio, 3),
                "oos_trades": oos_r.total_trades,
            }
        )

    if not oos_results:
        print("[MNQ-R7] No OOS results.")
        return {}

    # Fixed-params sweep on full dataset
    print(f"\n[MNQ-R7] Fixed-params sweep ({n_combos} combos on full dataset)...")
    fp_pfs = []
    for p in grid:
        try:
            r = _run(df, *p)
            if r.total_trades >= MIN_OOS_TRADES:
                fp_pfs.append(r.profit_factor)
        except Exception:
            pass
    fixed_metrics = {
        "fixed_params_min_pf": round(float(min(fp_pfs)), 4) if fp_pfs else 0.0,
        "fixed_params_mean_pf": round(float(np.mean(fp_pfs)), 4) if fp_pfs else 0.0,
        "fixed_params_max_pf": round(float(max(fp_pfs)), 4) if fp_pfs else 0.0,
    }
    print(
        f"  min_pf={fixed_metrics['fixed_params_min_pf']}  "
        f"mean_pf={fixed_metrics['fixed_params_mean_pf']}  "
        f"max_pf={fixed_metrics['fixed_params_max_pf']}"
    )

    gate = _gate_v2(oos_results, n_combos, fixed_metrics)

    print(f"\n{'='*65}")
    print(f"=== GATE v2: {gate['verdict']} ===")
    for k, need in [
        ("pf_ci_lower", f">= {GATE_PF_CI_LOWER}"),
        ("p_edge", f">= {GATE_P_EDGE}"),
        ("mc_95th_dd", f"<= {GATE_MC_DD_CORE}"),
        ("dsr", f">= {GATE_DSR}"),
    ]:
        print(f"  {k:20s} = {gate[k]:.4f}  (need {need})")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (ALT needs >= {GATE_FIXED_PARAMS_MIN_PF})"
    )
    print(f"{'='*65}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_doc = {
        "symbol": "MNQ",
        "family": "breakout",
        "rank": 7,
        "verdict": gate["verdict"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "params_fixed": {"stop_atr_mult": STOP_ATR_MULT, "vol_ma_period": VOL_MA_PERIOD},
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "grid_combos": n_combos,
            "grid": {
                "donchian": DONCHIAN_PERIOD_VALUES,
                "ema": EMA_TREND_PERIOD_VALUES,
                "atr_mult": ATR_REGIME_MULT_VALUES,
                "vol_mult": VOL_MULT_VALUES,
            },
        },
        "gate_v2_metrics": {**gate, **fixed_metrics},
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr": GATE_DSR,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
        },
        "windows": win_records,
        "lineage": {
            "rank6": "FAIL — pf_ci_lower=0.41, p_edge=0.0, wfo_consistency=WEAK",
            "rank6_root_cause": "atr_regime_mult>=1.0 cut signal so hard p_edge=0.0 across all windows",
            "rank7_hypothesis": "Lower ATR floor [0.5,0.75] + ema=0 baseline + wider donchian + vol_mult grid",
        },
    }
    vf = verdicts_dir / "MNQ_breakout_rank7.json"
    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    verdict_doc = _ip(verdict_doc, df=df)
    vf.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"[MNQ-R7] Verdict -> {vf}")
    return verdict_doc


def main():
    v = run_wfo()
    if not v:
        sys.exit(1)
    verdict = v.get("verdict", "FAIL")
    if verdict == "PASS":
        print("\n[PASS] Rank 7 PASSES gate v2 (CORE). MNQ regime filter confirmed.")
        print("Next: remove MNQ from DO_NOT_TRADE_SYMBOLS; deploy best WFO params.")
    elif verdict == "PASS_ALT":
        print("\n[PASS-ALT] Rank 7 PASSES gate v2 (ALT — $50K+ accounts).")
    else:
        print("\n[FAIL] Rank 7 FAILS gate v2.")
        print("ATR gate floor adjustment insufficient. Consider:")
        print("  - Multi-timeframe confirmation (4h trend + 1h entry)")
        print("  - Abandoning breakout family; try mean-reversion or ORB for MNQ")


if __name__ == "__main__":
    main()
