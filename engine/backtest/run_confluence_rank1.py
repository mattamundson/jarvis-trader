#!/usr/bin/env python
"""Confluence FADE experiment -- gate-v2 runner (Amo's 2026-05-30 5/29-chart challenge).

Tests the MULTI-FACTOR confluence the discretionary eye trades, NOT a single trigger:
fade an over-extension back toward value, taken ONLY when (1) price pokes outside the
prior session's value area, (2) the Corey Tscore confirms it's stretched (offsides), and
(3) price is beyond the Saty daily-ATR band. gate v2 already killed the single blind
triggers (tpo reversion, gap-fade); this is a genuinely different object.

Pre-registered: FADE direction only (no breakout A/B flip -> avoids the multiple-testing
trap). Grid is small on purpose (limits DSR n_trials): value_area_pct fixed at 0.70; the
swept confluence params are tscore_thr x atr_band_mult.

Path-loads the WORKTREE confluence_signals.py; its backtest.* imports (tpo_profile,
tpo_score, trend_signals._wilder_atr) resolve to the live engine via JARVIS_ENGINE_ROOT.
$50K ALT capital. Faithful 5m data (MES continuous).

Usage (from engine/):
    JARVIS_ENGINE_ROOT=<live engine>  JARVIS_CACHE_DIR=...  JARVIS_VERDICTS_DIR=...
    JARVIS_SYMBOL=MES  JARVIS_MULTIPLIER=5.0  JARVIS_DATA_FILE=MES_..._5m_cont.csv
    .venv/Scripts/python <worktree>/engine/backtest/run_confluence_rank1.py
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

# Path-load the WORKTREE confluence_signals.py; its backtest.* imports resolve via sys.path.
_cs_path = Path(__file__).resolve().parent / "confluence_signals.py"
_spec = importlib.util.spec_from_file_location("confluence_signals_wt", _cs_path)
_cs_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs_mod)
generate_confluence_signals = _cs_mod.generate_confluence_signals

SYMBOL = os.environ.get("JARVIS_SYMBOL", "MES").upper()
MULTIPLIER = float(os.environ.get("JARVIS_MULTIPLIER", "5.0"))
CAPITAL = 50_000.0
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0
FAMILY = "confluence"

# Pre-registered grid. value_area_pct FIXED 0.70 (standard auction). Swept confluence
# params kept tiny so DSR n_trials stays small: tscore_thr (LEAN vs CONTROL edge) x
# atr_band_mult (stretch in prior-day ATR; 1.0 = the chart's "+1 ATR").
VALUE_AREA_PCT = 0.70
TSCORE_THR_VALUES = [float(x) for x in os.environ.get("TSCORE_THRS", "0.33,0.66").split(",")]
ATR_BAND_MULT_VALUES = [float(x) for x in os.environ.get("ATR_BAND_MULTS", "0.5,1.0").split(",")]

# 5m intraday: train 6mo, test 2mo, step 1mo (overlapping -> more windows + adequate
# per-window OOS sample for a heavily-gated confluence signal).
TRAIN_MONTHS = int(os.environ.get("JARVIS_TRAIN_MONTHS", "6"))
TEST_MONTHS = int(os.environ.get("JARVIS_TEST_MONTHS", "2"))
STEP_MONTHS = int(os.environ.get("JARVIS_STEP_MONTHS", "1"))

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


def _bt(df, vap, tscore_thr, atr_band_mult, commission=COMMISSION, slippage_ticks=SLIPPAGE_TICKS):
    sig = generate_confluence_signals(
        df,
        value_area_pct=vap,
        tscore_thr=tscore_thr,
        atr_band_mult=atr_band_mult,
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
    for vap, tthr, abm in grid:
        try:
            r = _bt(df_train, vap, tthr, abm)
        except Exception as exc:
            print(f"    [WARN] IS error (vap={vap},tthr={tthr},abm={abm}): {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf = r.profit_factor
            best_p = {"value_area_pct": vap, "tscore_thr": tthr, "atr_band_mult": abm}
            best_res = r
    return best_p, best_res


def _fixed_sweep(df, grid):
    pfs, combos = [], []
    for vap, tthr, abm in grid:
        try:
            r = _bt(df, vap, tthr, abm)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combos.append(
                    {
                        "value_area_pct": vap,
                        "tscore_thr": tthr,
                        "atr_band_mult": abm,
                        "pf": round(r.profit_factor, 4),
                        "trades": r.total_trades,
                    }
                )
                print(
                    f"    combo (vap={vap},tthr={tthr},abm={abm}): PF={r.profit_factor:.4f} t={r.total_trades}"
                )
            else:
                print(
                    f"    combo (vap={vap},tthr={tthr},abm={abm}): SKIP ({r.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-sweep (vap={vap},tthr={tthr},abm={abm}): {exc}")
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
                champ["value_area_pct"],
                champ["tscore_thr"],
                champ["atr_band_mult"],
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
    print(f"[{SYMBOL}-CONFLUENCE] {data_file.name}")
    df = _load_data(data_file)
    print(
        f"[{SYMBOL}-CONFLUENCE] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}"
    )

    windows = _generate_windows(df)
    if not windows:
        print("ERROR: no windows")
        return {}
    grid = list(itertools.product([VALUE_AREA_PCT], TSCORE_THR_VALUES, ATR_BAND_MULT_VALUES))
    n_combos = len(grid)
    tf = "5m" if "_5m" in data_file.name else ("1h" if "_1h" in data_file.name else "?")
    print(
        f"=== {SYMBOL} CONFLUENCE-FADE | windows={len(windows)} | grid={n_combos} | {tf} bars ==="
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
            oos = _bt(
                df_test, best_p["value_area_pct"], best_p["tscore_thr"], best_p["atr_band_mult"]
            )
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
        print(f"[{SYMBOL}-CONFLUENCE] No OOS results (confluence gate may be too aggressive).")
        return {
            "symbol": SYMBOL,
            "family": FAMILY,
            "rank": 1,
            "verdict": "FAIL",
            "degenerate": True,
        }

    print(f"[{SYMBOL}-CONFLUENCE] fixed sweep...")
    fixed_m = _fixed_sweep(df, grid)
    votes = Counter(
        (
            r["best_params"]["value_area_pct"],
            r["best_params"]["tscore_thr"],
            r["best_params"]["atr_band_mult"],
        )
        for r in window_records
    )
    champ_t = (
        votes.most_common(1)[0][0]
        if votes
        else (VALUE_AREA_PCT, TSCORE_THR_VALUES[0], ATR_BAND_MULT_VALUES[0])
    )
    champ = {"value_area_pct": champ_t[0], "tscore_thr": champ_t[1], "atr_band_mult": champ_t[2]}
    print(f"[{SYMBOL}-CONFLUENCE] cost sweep (champ={champ})...")
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
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
            "grid_value_area_pct": [VALUE_AREA_PCT],
            "grid_tscore_thr": TSCORE_THR_VALUES,
            "grid_atr_band_mult": ATR_BAND_MULT_VALUES,
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
        "champion_params": champ,
        "windows": window_records,
        "lineage": {
            "experiment": "generation-engine: confluence FADE (Tscore + TPO value + Saty ATR)",
            "mechanical_rule": "fade_value_extreme_at_3factor_confluence",
            "conditioning": "value_extreme + tscore_offsides + saty_atr_stretch",
            "data_file": data_file.name,
            "bar_timeframe": tf,
            "data_span": f"{df.index.min().date()} -> {df.index.max().date()}",
            "thesis_note": (
                "Mechanizes Amo's 2026-05-30 discretionary read (5/29 /ES 5m): the edge is a "
                "MULTI-FACTOR confluence at a value extreme, not a single trigger. FADE-only, "
                "direction pre-registered. The single blind triggers already FAILED gate v2 "
                "(tpo reversion, gap-fade); this tests whether the confluence survives."
            ),
            "geometry_note": "Entry-anchored value-area-width R exits (stop 0.40R, T 0.60/1.20/1.80R, R:R_1=1.5) -- same trap-free geometry as tpo_signals.",
            "baseline": "trend family is the only prior gate-v2 PASS (MES/MGC); confluence is a new composite base family.",
        },
    }
    verdict_file.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[{SYMBOL}-CONFLUENCE] verdict -> {verdict_file}")
    return doc


if __name__ == "__main__":
    v = run_wfo()
    if not v:
        sys.exit(1)
    print(f"\n[{v['verdict']}] {SYMBOL} confluence-fade -- mechanized discretionary read.")
