#!/usr/bin/env python
"""
Trend + ADX trend-strength conditioner -- GENERATION-ENGINE EXPERIMENT 5.

The proposal ranker's Tier B is starved for NOVEL conditioner seeds -- it can
only score conditioners already in the corpus (none / rv_filter / vix_filter).
ADX/trend-strength has no prior and needs a human seed (the ranker says so
explicitly). This is that seed.

THESIS: `trend` is the ONLY family with a real gate-v2 edge (MES/MGC). The SMA
golden cross fires in chop as well as in trends; gating it on Wilder ADX (only
take the cross when the market is ACTUALLY trending) should concentrate the
proven trend edge. ADX is the canonical trend-strength gate; rv_filter and
vix_filter already showed regime conditioning can lift the trend family.

Mirrors run_mes_trend_rv_filter.py exactly except the conditioner: a FIXED,
thesis-driven adx_min (Wilder's classic ~20-25 "trend present"; NOT gridded --
gridding the conditioner threshold snoops it and inflates the DSR n_trials).
The trend param grid (fast x slow x atr_trail) and per-symbol WFO config match
each instrument's validated champion run, so the only new variable is the ADX gate.

Path-loads the WORKTREE trend_signals.py (which carries the additive default-off
adx_min/adx_period params); all other backtest.* imports resolve to the live
engine via JARVIS_ENGINE_ROOT. $50K ALT capital.

Usage (from engine/):
    JARVIS_ENGINE_ROOT=<live engine>  JARVIS_CACHE_DIR=...  JARVIS_VERDICTS_DIR=...
    JARVIS_SYMBOL=MES  JARVIS_MULTIPLIER=5.0  ADX_MIN=20
    .venv/Scripts/python <worktree>/engine/backtest/run_trend_adx_rank1.py
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(os.environ.get("JARVIS_ENGINE_ROOT", str(Path(__file__).resolve().parents[1])))
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# Path-load the WORKTREE trend_signals.py (has the additive adx_min param). It
# imports only numpy/pandas, so it loads standalone.
_ts_path = Path(__file__).resolve().parent / "trend_signals.py"
_spec = importlib.util.spec_from_file_location("trend_signals_wt", _ts_path)
_ts_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ts_mod)
generate_sma_trend_signals = _ts_mod.generate_sma_trend_signals

SYMBOL = os.environ.get("JARVIS_SYMBOL", "MES").upper()
MULTIPLIER = float(os.environ.get("JARVIS_MULTIPLIER", "5.0"))
CAPITAL = 50_000.0
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

ADX_MIN = float(os.environ.get("ADX_MIN", "20.0"))  # FIXED conditioner threshold (Wilder ~20)
ADX_PERIOD = int(os.environ.get("ADX_PERIOD", "14"))
# RV_MIN > 0 STACKS the realized-vol conditioner on top of ADX (P3). When both are on the
# family is "trend_adx_rv_filter" -> ledger parses cond="adx_filter+rv_filter". generate_sma_
# trend_signals applies both gates independently. RV annualization factor is 1h (module default).
RV_MIN = float(os.environ.get("RV_MIN", "0.0"))
_conds = [("adx", ADX_MIN > 0)] + [("rv", RV_MIN > 0)]
_on = [seg for seg, active in _conds if active]
FAMILY = "trend" + "".join(f"_{s}" for s in _on) + ("_filter" if _on else "")

# Per-symbol trend grid + WFO config -- mirror each instrument's validated champion.
_SYM_CFG = {
    "MES": {
        "fast": [50, 55, 60],
        "slow": [200],
        "atr": [2.0],
        "train": 6,
        "test": 1,
        "step": 1,
    },
    "MGC": {
        "fast": [40, 50],
        "slow": [80, 120],
        "atr": [1.5, 2.0],
        "train": 6,
        "test": 2,
        "step": 1,
    },
}
_cfg = _SYM_CFG.get(SYMBOL, _SYM_CFG["MES"])
FAST_VALUES = _cfg["fast"]
SLOW_VALUES = _cfg["slow"]
ATR_VALUES = _cfg["atr"]
TRAIN_MONTHS = int(os.environ.get("JARVIS_TRAIN_MONTHS", str(_cfg["train"])))
TEST_MONTHS = int(os.environ.get("JARVIS_TEST_MONTHS", str(_cfg["test"])))
STEP_MONTHS = int(os.environ.get("JARVIS_STEP_MONTHS", str(_cfg["step"])))

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}
MIN_OOS_TRADES_PER_WINDOW = 1

CACHE_DIR = Path(os.environ.get("JARVIS_CACHE_DIR", str(engine_root / "backtest" / "cache")))
VERDICTS_DIR = Path(
    os.environ.get("JARVIS_VERDICTS_DIR", str(engine_root / "data" / "gate_v2_verdicts"))
)

from backtest._constants import (  # noqa: E402
    COST_TIER_ORDER,
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)
from backtest.backtester import Backtester  # noqa: E402


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start, data_end = df.index.min(), df.index.max()
    windows, cursor, wnum = [], data_start, 1
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=TEST_MONTHS)
        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end
        df_train = df[(df.index >= train_start) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]
        if len(df_train) >= 30 and len(df_test) >= 30:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                }
            )
            wnum += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= data_end:
            break
    return windows


def _bt(df, fast, slow, atr_trail, commission=COMMISSION, slippage_ticks=SLIPPAGE_TICKS):
    sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail,
        adx_min=ADX_MIN,
        adx_period=ADX_PERIOD,
        min_rv_annualized=RV_MIN,
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
    )
    return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _best_is(df_train, grid):
    best_pf, best_p, best_res = -1.0, None, None
    for fast, slow, atr_trail in grid:
        try:
            r = _bt(df_train, fast, slow, atr_trail)
        except Exception as exc:
            print(f"    [WARN] IS error ({fast},{slow},{atr_trail}): {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf = r.profit_factor
            best_p = {"fast": fast, "slow": slow, "atr_trail_mult": atr_trail}
            best_res = r
    return best_p, best_res


def _fixed_sweep(df, grid):
    pfs, combos = [], []
    for fast, slow, atr_trail in grid:
        try:
            r = _bt(df, fast, slow, atr_trail)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combos.append(
                    {
                        "fast": fast,
                        "slow": slow,
                        "atr_trail_mult": atr_trail,
                        "pf": round(r.profit_factor, 4),
                        "trades": r.total_trades,
                    }
                )
                print(
                    f"    combo ({fast},{slow},{atr_trail}): PF={r.profit_factor:.4f} t={r.total_trades}"
                )
            else:
                print(f"    combo ({fast},{slow},{atr_trail}): SKIP ({r.total_trades} trades)")
        except Exception as exc:
            print(f"  [WARN] fixed-sweep ({fast},{slow},{atr_trail}): {exc}")
    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combos,
        }
    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combos,
    }


def _cost_sweep(df, champ):
    results, last = {}, None
    for tier in COST_TIER_ORDER:
        ct = COST_SWEEP_TIERS[tier]
        try:
            r = _bt(
                df,
                champ["fast"],
                champ["slow"],
                champ["atr_trail_mult"],
                commission=ct["commission"],
                slippage_ticks=ct["slippage_ticks"],
            )
            passes = r.profit_factor > 1.0 and r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {
                "pf": round(r.profit_factor, 4),
                "trades": r.total_trades,
                "passes": passes,
            }
            print(
                f"    [{tier:12s}] PF={r.profit_factor:.4f} t={r.total_trades} {'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last = tier
        except Exception as exc:
            print(f"  [WARN] cost {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last or "none", "tier_results": results}


def _gate(oos_results, n_combos, fixed_m, cost_m):
    from backtest.deflated_sharpe import deflated_sharpe_ratio

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    oos_sharpes = [
        r.sharpe_ratio for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
    ]
    all_trades = sum(r.total_trades for r in oos_results)
    pf_ci = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    mean_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    dsr_r = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_combos, n_obs=max(all_trades, 30))
    dsr = dsr_r.get("dsr", 0.0) if isinstance(dsr_r, dict) else float(dsr_r)
    wfo = _classify_wfo_consistency(oos_pfs)
    fpf = fixed_m.get("fixed_params_min_pf", 0.0)
    cost = cost_m.get("cost_survives_through", "none")
    cost_idx = COST_TIER_ORDER.index(cost) if cost in COST_TIER_ORDER else -1
    cost_pass = cost_idx >= COST_TIER_ORDER.index("realistic")
    core = (
        pf_ci >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt = (
        dsr >= GATE_DSR_ALT
        and wfo in GATE_WFO_CONSISTENCY_VALUES
        and fpf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_pass
        and mc_dd <= GATE_MC_DD_ALT
    )
    verdict = "PASS" if (core or alt) else "FAIL"
    return {
        "verdict": verdict,
        "passed_via": "core" if core else ("alt" if alt else None),
        "core_verdict": "PASS" if core else "FAIL",
        "alt_verdict": "PASS" if alt else "FAIL",
        "pf_ci_lower": round(pf_ci, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_dd, 6),
        "mc_95th_dd_pct": round(mc_dd * 100, 4),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo,
        "fixed_params_min_pf": fpf,
        "fixed_params_mean_pf": fixed_m.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_m.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
    }


def run_wfo() -> dict:
    from backtest._gate_v2_helpers import _find_latest_cache

    override = os.environ.get("JARVIS_DATA_FILE")
    if override:
        data_file = Path(override)
        if not data_file.is_absolute():
            data_file = CACHE_DIR / data_file
    else:
        data_file = _find_latest_cache(CACHE_DIR, SYMBOL)
    print(f"[{SYMBOL}-TREND-ADX{ADX_MIN:.0f}] {data_file.name}")
    df = _load_data(data_file)
    print(
        f"[{SYMBOL}-TREND-ADX] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}"
    )

    windows = _generate_windows(df)
    if not windows:
        print("ERROR: no windows")
        return {}
    grid = list(itertools.product(FAST_VALUES, SLOW_VALUES, ATR_VALUES))
    n_combos = len(grid)
    tf = (
        "1h"
        if "_1h" in data_file.name
        else ("1d" if "_1d" in data_file.name else ("5m" if "_5m" in data_file.name else "?"))
    )
    print(
        f"=== {SYMBOL} TREND+ADX(>={ADX_MIN:.0f}) | windows={len(windows)} | grid={n_combos} | {tf} bars ==="
    )

    oos_results, window_records = [], []
    for win in windows:
        ts, te, os_, oe = win["train_start"], win["train_end"], win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        best_p, is_res = _best_is(df_train, grid)
        if best_p is None:
            print(f"Window {win['window_num']}: [SKIP] no valid IS params")
            continue
        try:
            oos = _bt(df_test, best_p["fast"], best_p["slow"], best_p["atr_trail_mult"])
        except Exception as exc:
            print(f"Window {win['window_num']}: [SKIP] OOS err {exc}")
            continue
        print(
            f"Window {win['window_num']}: IS {best_p} PF={is_res.profit_factor:.2f} "
            f"t={is_res.total_trades} | OOS PF={oos.profit_factor:.2f} t={oos.total_trades}"
        )
        oos_results.append(oos)
        window_records.append(
            {
                "window": win["window_num"],
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_params": best_p,
                "is_pf": round(is_res.profit_factor, 3),
                "is_trades": is_res.total_trades,
                "oos_pf": round(oos.profit_factor, 3),
                "oos_dd": round(oos.max_drawdown_pct, 4),
                "oos_sharpe": round(oos.sharpe_ratio, 3),
                "oos_trades": oos.total_trades,
            }
        )

    if not oos_results:
        print(f"[{SYMBOL}-TREND-ADX] No OOS results (ADX gate may be too aggressive).")
        return {
            "symbol": SYMBOL,
            "family": FAMILY,
            "rank": 1,
            "verdict": "FAIL",
            "degenerate": True,
        }

    print(f"[{SYMBOL}-TREND-ADX] fixed sweep...")
    fixed_m = _fixed_sweep(df, grid)
    votes = Counter(
        (r["best_params"]["fast"], r["best_params"]["slow"], r["best_params"]["atr_trail_mult"])
        for r in window_records
    )
    champ_t = (
        votes.most_common(1)[0][0] if votes else (FAST_VALUES[0], SLOW_VALUES[0], ATR_VALUES[0])
    )
    champ = {"fast": champ_t[0], "slow": champ_t[1], "atr_trail_mult": champ_t[2]}
    print(f"[{SYMBOL}-TREND-ADX] cost sweep (champ={champ})...")
    cost_m = _cost_sweep(df, champ)
    gate = _gate(oos_results, n_combos, fixed_m, cost_m)

    print(f"\n=== GATE v2: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    for k in (
        "pf_ci_lower",
        "p_edge",
        "mc_95th_dd_pct",
        "dsr",
        "wfo_consistency",
        "fixed_params_min_pf",
        "cost_survives_through",
        "total_oos_trades",
    ):
        print(f"  {k:22}= {gate[k]}")

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    verdict_file = VERDICTS_DIR / f"{SYMBOL}_{FAMILY}_rank1.json"
    doc = {
        "symbol": SYMBOL,
        "family": FAMILY,
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "adx_filter_config": {"adx_min": ADX_MIN, "adx_period": ADX_PERIOD},
        "rv_filter_config": {"min_rv_annualized": RV_MIN} if RV_MIN > 0 else None,
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
            "grid_fast_period": FAST_VALUES,
            "grid_slow_period": SLOW_VALUES,
            "grid_atr_trail_mult": ATR_VALUES,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed_m.get("n_combos_with_trades", 0),
            "combo_results": fixed_m.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_m.get("tier_results", {}),
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr_core": GATE_DSR,
            "dsr_alt": GATE_DSR_ALT,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
            "wfo_consistency_alt": GATE_WFO_CONSISTENCY_VALUES,
            "cost_survives_through_min": "realistic",
        },
        "champion_params": {
            **champ,
            "adx_min": ADX_MIN,
            "adx_period": ADX_PERIOD,
            **({"min_rv_annualized": RV_MIN} if RV_MIN > 0 else {}),
        },
        "windows": window_records,
        "lineage": {
            "experiment": (
                "generation-engine experiment 6: trend + ADX + RV stacked conditioners"
                if RV_MIN > 0
                else "generation-engine experiment 5: trend + ADX trend-strength conditioner"
            ),
            "mechanical_rule": "sma_golden_cross_long",
            "conditioning": (
                f"adx_filter(min={ADX_MIN},period={ADX_PERIOD})"
                + (f" + rv_filter(min_ann={RV_MIN})" if RV_MIN > 0 else "")
            ),
            "data_file": data_file.name,
            "bar_timeframe": tf,
            "data_span": f"{df.index.min().date()} -> {df.index.max().date()}",
            "conditioner_note": (
                "FIXED thesis-driven adx_min (Wilder ~20 'trend present'); NOT gridded -- "
                "gridding the conditioner threshold would snoop it and inflate DSR n_trials. "
                "Trend grid + WFO config mirror the validated champion run; ADX is the only new variable."
            ),
            "kill_switch_note": "fixed_params_min_pf is depressed by the -5% max-DD kill switch "
            "halting the single full-series backtest early; per-window OOS p_edge/pf_ci are reliable.",
            "baseline": "trend family is the only gate-v2 PASS (MES/MGC); this seeds the adx_filter conditioner.",
        },
    }
    verdict_file.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[{SYMBOL}-TREND-ADX] verdict -> {verdict_file}")
    return doc


if __name__ == "__main__":
    v = run_wfo()
    if not v:
        sys.exit(1)
    print(
        f"\n[{v['verdict']}] {SYMBOL} trend+ADX({ADX_MIN:.0f}) -- first adx_filter conditioner verdict."
    )
