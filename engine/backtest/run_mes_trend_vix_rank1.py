#!/usr/bin/env python
"""
MES Trend VIX-Conditional Gate v2 — Rank 1

Hypothesis: Filtering SMA(60,200) MES golden-cross entries to bars where VIX is
in [vix_min, vix_max] concentrates the trend edge in the "normal volatility"
regime and avoids complacency (VIX<13) and crisis (VIX>30) entries.

Method:
  - SMA trend params FIXED at rank11 champion: fast=60, slow=200, atr_trail_mult=2.0
  - Grid over VIX_MIN_VALUES × VIX_MAX_VALUES (9 combos: 3×3)
  - VIX data loaded via yfinance (^VIX daily close, 2022-01-01 to present)
  - VIX is forward-filled to 1h MES bars (same-day alignment, no lookahead)
  - Gate v2 ALT PASS of at least one (vix_min, vix_max) combo writes a verdict

Grid:
  VIX_MIN_VALUES = [12, 13, 14]
  VIX_MAX_VALUES = [28, 30, 32]
  9 × 1 × 1 × 1 = 9 combos (VIX params only; SMA params fixed at champion)

Goal: push p_edge toward CORE threshold (0.95) by suppressing low-quality signals.
  rank11 baseline: p_edge=0.75 (ALT PASS), target: p_edge>=0.85 (better ALT) or >=0.95 (CORE)

Writes: engine/data/gate_v2_verdicts/MES_trend_vix_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_trend_vix_rank1.py

Requires yfinance:
    .venv/Scripts/pip install yfinance
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 50_000.0
TICK_SIZE = 0.25
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1
N_WINDOWS = 18

# SMA params FIXED at rank11 champion — not part of the grid
FAST = 60
SLOW = 200
ATR_TRAIL_MULT = 2.0

# VIX filter grid — the variable being optimized
VIX_MIN_VALUES = [12, 13, 14]
VIX_MAX_VALUES = [28, 30, 32]

MIN_OOS_TRADES_PER_WINDOW = 1

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}


# ---------------------------------------------------------------------------
# VIX data loading
# ---------------------------------------------------------------------------


def _load_vix_data(start: str = "2022-01-01") -> pd.DataFrame:
    """Load VIX daily close via yfinance. Returns DataFrame with 'close' column."""
    try:
        import yfinance as yf
    except ImportError:
        print("[ERROR] yfinance not installed. Run: .venv/Scripts/pip install yfinance")
        sys.exit(1)

    print(f"[VIX] Downloading ^VIX daily from {start} ...")
    vix = yf.download("^VIX", start=start, progress=False, auto_adjust=True)
    if vix.empty:
        print("[ERROR] yfinance returned empty VIX data.")
        sys.exit(1)

    vix.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in vix.columns]
    _vidx = pd.to_datetime(vix.index)
    if getattr(_vidx, "tz", None) is not None:
        _vidx = _vidx.tz_localize(None)  # some yfinance versions return tz-aware UTC
    vix.index = _vidx.normalize()
    print(
        f"[VIX] {len(vix)} bars | {vix.index.min().date()} -> {vix.index.max().date()} "
        f"| current: {vix['close'].iloc[-1]:.2f}"
    )
    return vix[["close"]]


# ---------------------------------------------------------------------------
# MES data loading
# ---------------------------------------------------------------------------


def _load_mes_data(data_dir: Path) -> pd.DataFrame:
    from backtest._gate_v2_helpers import _find_latest_cache

    data_file = _find_latest_cache(data_dir, "MES")
    print(f"[MES] Selected {data_file.name}")
    df = pd.read_csv(data_file)
    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    _ts = pd.to_datetime(df[ts_col])
    # Some caches are written tz-aware UTC (datetime64[us, UTC]); the tz-naive VIX
    # daily frame then fails to reindex against it inside generate_sma_trend_signals
    # ("Cannot compare dtypes ... UTC"). Drop tz, preserving the UTC wall-clock time.
    if getattr(_ts.dt, "tz", None) is not None:
        _ts = _ts.dt.tz_localize(None)
    df[ts_col] = _ts
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    print(f"[MES] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# Window generation (identical to rank11)
# ---------------------------------------------------------------------------


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start = df.index.min()
    data_end = df.index.max()
    windows = []
    cursor = data_start
    wnum = 1
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
                    "n_train": len(df_train),
                    "n_test": len(df_test),
                }
            )
            wnum += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= data_end:
            break
    return windows


# ---------------------------------------------------------------------------
# Signal + backtest (VIX-aware)
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    vix_min: float,
    vix_max: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=FAST,
        slow=SLOW,
        atr_trail_mult=ATR_TRAIL_MULT,
        vix_df=vix_df,
        vix_min=vix_min,
        vix_max=vix_max,
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
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


# ---------------------------------------------------------------------------
# IS grid search — over VIX params (SMA params fixed)
# ---------------------------------------------------------------------------


def _best_is_vix_params(
    df_train: pd.DataFrame,
    vix_df: pd.DataFrame,
    grid: list[tuple],
) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None

    for vix_min, vix_max in grid:
        try:
            result = _run_signals_and_backtest(df_train, vix_df, vix_min, vix_max)
        except Exception as exc:
            print(f"    [WARN] IS error vix=[{vix_min},{vix_max}]: {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"vix_min": vix_min, "vix_max": vix_max}
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 helpers
# ---------------------------------------------------------------------------

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
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


def _run_fixed_params_sweep(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    grid: list[tuple],
) -> dict:
    """Fixed-params sweep across all VIX combos on the full dataset."""
    pfs = []
    combo_results = []
    for vix_min, vix_max in grid:
        try:
            result = _run_signals_and_backtest(df, vix_df, vix_min, vix_max)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "vix_min": vix_min,
                        "vix_max": vix_max,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    VIX=[{vix_min:2.0f},{vix_max:2.0f}]: "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    VIX=[{vix_min:2.0f},{vix_max:2.0f}]: "
                    f"SKIP (only {result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error VIX=[{vix_min},{vix_max}]: {exc}")

    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combo_results,
        }

    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combo_results,
    }


def _run_cost_sweep(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    champion_vix: dict,
) -> dict:
    results = {}
    last_surviving = None

    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                vix_df,
                vix_min=champion_vix["vix_min"],
                vix_max=champion_vix["vix_max"],
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  "
                f"PF={pf:.4f}  trades={result.total_trades}  "
                f"{'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last_surviving = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}

    return {"cost_survives_through": last_surviving or "none", "tier_results": results}


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (a 1-2 trade window's giant Sharpe deflated to a fake ~1.0 and
    # auto-passed both gate floors). See _gate_v2_trade_metrics for the why.
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)

    wfo_consistency = _classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")

    cost_tier_idx = (
        COST_TIER_ORDER.index(cost_survives_through)
        if cost_survives_through in COST_TIER_ORDER
        else -1
    )
    cost_realistic_idx = COST_TIER_ORDER.index("realistic")
    cost_passes = cost_tier_idx >= cost_realistic_idx

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    if core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo() -> dict:
    data_dir = engine_root / "backtest" / "cache"
    df = _load_mes_data(data_dir)
    vix_df = _load_vix_data(start=str(df.index.min().date()))

    windows = _generate_windows(df)
    if not windows:
        print("[MES-VIX-R1] ERROR: not enough data to form windows.")
        return {}

    # VIX-only grid: SMA params fixed at rank11 champion
    vix_grid = list(itertools.product(VIX_MIN_VALUES, VIX_MAX_VALUES))
    n_combos = len(vix_grid)

    print(f"\n{'=' * 70}")
    print("=== MES TREND VIX RANK 1 — VIX FILTER GRID [12/13/14] × [28/30/32] ===")
    print(f"SMA fixed: fast={FAST}, slow={SLOW}, atr_trail_mult={ATR_TRAIL_MULT} (rank11 champion)")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} VIX combos")
    print(f"  vix_min: {VIX_MIN_VALUES}  vix_max: {VIX_MAX_VALUES}")
    print("Rank11 baseline: p_edge=0.75, mc_dd=0.81%, dsr=1.0  (target: p_edge >= 0.85)")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]

        print(
            f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  "
            f"({win['n_train']} / {win['n_test']} bars)"
        )

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_vix_params(df_train, vix_df, vix_grid)

        if best_params is None:
            print(
                f"  [SKIP] No valid IS VIX params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)"
            )
            continue

        print(
            f"  Best IS: VIX=[{best_params['vix_min']},{best_params['vix_max']}]  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                vix_df,
                vix_min=best_params["vix_min"],
                vix_max=best_params["vix_max"],
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(
            f"  OOS:     PF={oos_result.profit_factor:.2f}  "
            f"DD={oos_result.max_drawdown_pct:.1%}  "
            f"Sharpe={oos_result.sharpe_ratio:.2f}  "
            f"trades={oos_result.total_trades}"
        )

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": wnum,
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_vix_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("\n[MES-VIX-R1] No OOS results — WFO aborted.")
        return {}

    # Fixed-params sweep (ALT metric)
    print(f"\n[MES-VIX-R1] Running fixed-params sweep on full dataset ({n_combos} VIX combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, vix_df, vix_grid)
    print(
        f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep (ALT metric) — use most-selected VIX combo as champion
    param_votes = Counter(
        (r["best_vix_params"]["vix_min"], r["best_vix_params"]["vix_max"]) for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (13, 30)
    champion_vix = {"vix_min": most_selected[0], "vix_max": most_selected[1]}
    print(
        f"\n[MES-VIX-R1] Running cost sweep (champion: VIX=[{champion_vix['vix_min']},"
        f"{champion_vix['vix_max']}])..."
    )
    cost_sweep_metrics = _run_cost_sweep(df, vix_df, champion_vix)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

    # Gate v2 verdict
    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (rank11 baseline: 0.75)")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%")
    print(f"  dsr                  = {gate['dsr']:.6f}")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}")
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MES_trend_vix_rank1.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend_vix",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "sma_params": {
            "fast": FAST,
            "slow": SLOW,
            "atr_trail_mult": ATR_TRAIL_MULT,
            "note": "Fixed at rank11 champion — VIX filter is the only variable",
        },
        "champion_vix_params": champion_vix,
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
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "combo_results": fixed_params_metrics.get("combo_results", []),
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "vix_min_values": VIX_MIN_VALUES,
            "vix_max_values": VIX_MAX_VALUES,
            "n_combos": n_combos,
        },
        "lineage": {
            "baseline": "MES_trend_rank11",
            "baseline_p_edge": 0.75,
            "baseline_verdict": "PASS via alt",
            "hypothesis": "VIX filter [vix_min, vix_max] concentrates trend edge in normal-vol regime",
            "target_improvement": "p_edge >= 0.85 (better ALT) or >= 0.95 (CORE PASS)",
        },
        "windows": window_records,
    }

    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    verdict_doc = _ip(verdict_doc, df=df)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-VIX-R1] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MES-VIX-R1] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MES Trend VIX Rank 1 PASSES gate v2 (CORE path).")
        print(f"  p_edge={gate.get('p_edge', '?')} >= {GATE_P_EDGE} — CORE threshold reached!")
        print("  VIX filter confirmed to push edge above core bar.")
    elif final == "PASS" and passed_via == "alt":
        p = gate.get("p_edge", "?")
        print("\n[PASS-ALT] MES Trend VIX Rank 1 PASSES gate v2 (ALT path).")
        print(f"  p_edge={p} (rank11 baseline was 0.75).")
        if isinstance(p, float) and p >= 0.85:
            print("  Improvement confirmed — VIX filter raises p_edge meaningfully.")
        else:
            print("  Marginal improvement over rank11 baseline — consider wider VIX grid in rank2.")
    else:
        p = gate.get("p_edge", "?")
        print(f"\n[FAIL] MES Trend VIX Rank 1 FAILS gate v2. p_edge={p}")
        print("  VIX filter may be over-fitting or reducing too many trades.")
        print("  Consider wider vix_max (35-40) or loosening vix_min to 10 in rank2.")

    print(f"  Champion VIX params: {verdict.get('champion_vix_params')}")


if __name__ == "__main__":
    main()
