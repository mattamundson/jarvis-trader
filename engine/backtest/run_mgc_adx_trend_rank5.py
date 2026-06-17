#!/usr/bin/env python
"""
MGC (Micro Gold) Trend Gate v2 -- Rank 5: ADX(14) Entry Filter

Context:
    Rank 4 result: PASS-ALT, pf_ci_lower=2.59, mc_95th_dd~3.03%, dsr=1.0, ~67 OOS trades
    ADX discovery (commit 0b713a2, branch chore/discovery-scripts-2026-06-16):
        adx_threshold=18 on MGC 1h fast=50/slow=120/atr=2.0:
            -> PASS-ALT, pf_ci_lower~2.62, mc_95th_dd~1.83%, dsr=1.0, ~40 OOS trades
        Lower mc_95th_dd is the key improvement: 3.03% -> ~1.83% (well within 4% ALT ceiling).

Rank 5 hypothesis:
    Single fixed combo: fast=50, slow=120, atr_trail_mult=2.0, adx_threshold=18
    WFO config identical to rank4: TRAIN=6mo, TEST=2mo, STEP=1mo
    Grid = 1 combo (fixed params; ADX filter is the innovation being evaluated)

Safety:
    Writes to engine/backtest/adx_validation_verdicts/ ONLY.
    Never writes to gate_v2_verdicts/ or edge_ledger.jsonl.
    Does NOT modify signals.py, config.py, .env, or any live-routing code.
    Does NOT restart the engine or call any live endpoints.

Companion baseline run:
    adx_threshold=None reproduces bare rank4 single-combo baseline for direct comparison.

Usage (from engine/ directory, using main checkout venv):
    ../.venv/Scripts/python backtest/run_mgc_adx_trend_rank5.py
    ../.venv/Scripts/python backtest/run_mgc_adx_trend_rank5.py --adx-threshold 18
    ../.venv/Scripts/python backtest/run_mgc_adx_trend_rank5.py --baseline-only
    ../.venv/Scripts/python backtest/run_mgc_adx_trend_rank5.py --both
"""
from __future__ import annotations

import argparse
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
# Isolated output directory -- NEVER gate_v2_verdicts/
# ---------------------------------------------------------------------------

OUTPUT_DIR = engine_root / "backtest" / "adx_validation_verdicts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Contract + WFO constants (identical to rank4)
# ---------------------------------------------------------------------------

SYMBOL = "MGC"
MULTIPLIER = 10.0
CAPITAL = 50_000.0
TICK_SIZE = 0.10
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1

MIN_OOS_TRADES_PER_WINDOW = 1

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

# Canonical champion params (rank4 winner)
CHAMPION_FAST = 50
CHAMPION_SLOW = 120
CHAMPION_ATR = 2.0
ADX_PERIOD = 14

# ---------------------------------------------------------------------------
# Gate v2 imports (canonical -- do NOT reimplement)
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
    MIN_OOS_TRADES_TOTAL,
    _find_latest_cache,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
    sample_adequacy_enforced,
)
from backtest._gate_v2_trade_metrics import (  # noqa: E402
    trade_level_dsr,
    trade_level_mc_95th_dd,
    trade_level_win_rate_ci_lower,
)

# ---------------------------------------------------------------------------
# Data loading (identical to rank4)
# ---------------------------------------------------------------------------


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


def _find_data_file(data_dir: Path) -> Path:
    chosen = _find_latest_cache(data_dir, "MGC")
    print(f"[MGC-R5] Selected {chosen.name}")
    return chosen


# ---------------------------------------------------------------------------
# Window generation (identical to rank4)
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
# Signal + backtest (threads adx_threshold through to generate_sma_trend_signals)
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    atr_trail_mult: float,
    adx_threshold: float | None = None,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
):
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        adx_threshold=adx_threshold,
        adx_period=ADX_PERIOD,
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
# Fixed-params sweep (single combo for rank5 -- adx_threshold is fixed)
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(
    df: pd.DataFrame,
    adx_threshold: float | None,
) -> dict:
    """For rank5, the 'grid' is a single combo. Run it over the full dataset."""
    try:
        result = _run_signals_and_backtest(
            df,
            fast=CHAMPION_FAST,
            slow=CHAMPION_SLOW,
            atr_trail_mult=CHAMPION_ATR,
            adx_threshold=adx_threshold,
        )
        if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
            pf = result.profit_factor
            print(
                f"    combo ({CHAMPION_FAST},{CHAMPION_SLOW},{CHAMPION_ATR},adx={adx_threshold}): "
                f"PF={pf:.4f}  trades={result.total_trades}"
            )
            return {
                "fixed_params_min_pf": round(float(pf), 4),
                "fixed_params_mean_pf": round(float(pf), 4),
                "fixed_params_max_pf": round(float(pf), 4),
                "n_combos_with_trades": 1,
                "combo_results": [
                    {
                        "fast": CHAMPION_FAST,
                        "slow": CHAMPION_SLOW,
                        "atr_trail_mult": CHAMPION_ATR,
                        "adx_threshold": adx_threshold,
                        "pf": round(pf, 4),
                        "trades": result.total_trades,
                    }
                ],
            }
        else:
            print(
                f"    combo SKIP ({result.total_trades} trades < {MIN_OOS_TRADES_PER_WINDOW})"
            )
    except Exception as exc:
        print(f"  [WARN] fixed-params error: {exc}")

    return {
        "fixed_params_min_pf": 0.0,
        "fixed_params_mean_pf": 0.0,
        "fixed_params_max_pf": 0.0,
        "n_combos_with_trades": 0,
        "combo_results": [],
    }


# ---------------------------------------------------------------------------
# Cost sweep
# ---------------------------------------------------------------------------


def _run_cost_sweep(df: pd.DataFrame, adx_threshold: float | None) -> dict:
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                fast=CHAMPION_FAST,
                slow=CHAMPION_SLOW,
                atr_trail_mult=CHAMPION_ATR,
                adx_threshold=adx_threshold,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  PF={pf:.4f}  "
                f"trades={result.total_trades}  {'PASS' if passes else 'FAIL'}"
            )
            if survival_intact and passes:
                cost_survives_through = tier
            elif not passes:
                survival_intact = False
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
            survival_intact = False
    return {"cost_survives_through": cost_survives_through, "tier_results": results}


# ---------------------------------------------------------------------------
# Gate v2 evaluation (mirrors rank4 exactly)
# ---------------------------------------------------------------------------


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))

    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=CAPITAL)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)
    win_rate_ci_lower = trade_level_win_rate_ci_lower(oos_results)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    wfo_consistency = classify_wfo_consistency(oos_pfs)
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

    core_reasons = [
        f"{'FAIL ' if pf_ci_lower < GATE_PF_CI_LOWER else ''}mbb_pf_ci_lower={pf_ci_lower:.4f} >= {GATE_PF_CI_LOWER}",
        f"{'FAIL ' if p_edge < GATE_P_EDGE else ''}p_positive_edge={p_edge:.4f} >= {GATE_P_EDGE}",
        f"mc_95th_dd_pct={mc_95th_dd*100:.4f} {'<=' if mc_95th_dd<=GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE*100:.1f}",
        f"dsr={dsr:.6f} >= {GATE_DSR} (not selection-bias)",
    ]
    alt_reasons = [
        f"{'FAIL ' if dsr < GATE_DSR_ALT else ''}dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)",
        f"{'FAIL ' if wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES else ''}rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}",
        f"{'FAIL ' if fixed_params_min_pf < GATE_FIXED_PARAMS_MIN_PF else ''}fixed_params_min_pf={fixed_params_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}",
        f"{'FAIL ' if not cost_passes else ''}cost_survives_through={cost_survives_through} >= realistic",
        f"{'FAIL ' if mc_95th_dd > GATE_MC_DD_ALT else ''}mc_95th_dd_pct={mc_95th_dd*100:.4f} <= {GATE_MC_DD_ALT*100:.1f} (alt ceiling)",
    ]

    if sample_adequacy_enforced() and not sample_adequate:
        verdict, passed_via = "INSUFFICIENT_SAMPLE", None
    elif core_pass:
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
        "mc_95th_dd_window_legacy": round(mc_95th_dd_window_legacy, 6),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "min_oos_trades_total": MIN_OOS_TRADES_TOTAL,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo(adx_threshold: float | None, data_dir: Path | None = None) -> dict:
    label = f"adx{adx_threshold}" if adx_threshold is not None else "no_adx_baseline"
    if data_dir is None:
        # Primary: worktree's own cache. Fallback: main checkout cache.
        candidate = engine_root / "backtest" / "cache"
        main_checkout_cache = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache")
        if not any(candidate.glob("MGC_*_1h.csv")) and main_checkout_cache.exists():
            data_dir = main_checkout_cache
            print(f"[MGC-R5] Using main checkout cache: {data_dir}")
        else:
            data_dir = candidate
    data_file = _find_data_file(data_dir)

    print(f"\n[MGC-R5] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MGC-R5] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MGC-R5] ERROR: not enough data to form WFO windows.")
        return {}

    # Rank5: single combo (fixed champion params + adx_threshold)
    n_combos = 1

    print(f"\n{'=' * 70}")
    print(f"=== MGC TREND RANK5 ADX({ADX_PERIOD}) CONDITIONING -- {label.upper()} ===")
    print(
        f"Params: fast={CHAMPION_FAST} slow={CHAMPION_SLOW} atr={CHAMPION_ATR} "
        f"adx_threshold={adx_threshold}"
    )
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Output dir: {OUTPUT_DIR}")
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

        # Rank5 has only 1 combo -- no IS grid search needed.
        # Run the fixed params directly on each OOS window.
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                fast=CHAMPION_FAST,
                slow=CHAMPION_SLOW,
                atr_trail_mult=CHAMPION_ATR,
                adx_threshold=adx_threshold,
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(
            f"  OOS: PF={oos_result.profit_factor:.2f}  "
            f"DD={oos_result.max_drawdown_pct:.1%}  "
            f"Sharpe={oos_result.sharpe_ratio:.2f}  "
            f"trades={oos_result.total_trades}"
        )

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": wnum,
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("\n[MGC-R5] No OOS results -- WFO aborted.")
        return {}

    # Fixed-params sweep on full dataset
    print(f"\n[MGC-R5] Fixed-params sweep on full dataset ({n_combos} combo)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, adx_threshold)

    # Cost sweep (fixed champion -- adx_threshold carries through)
    print(f"\n[MGC-R5] Cost sweep (adx_threshold={adx_threshold})...")
    cost_sweep_metrics = _run_cost_sweep(df, adx_threshold)
    print(
        f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  "
        f"(need >= 'realistic')"
    )

    # Gate v2
    gate = _compute_gate_v2(oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  adx_threshold        = {adx_threshold}")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd_pct       = {gate['mc_95th_dd_pct']:.4f}%  "
        f"(core <= {GATE_MC_DD_CORE*100:.0f}% / alt <= {GATE_MC_DD_ALT*100:.0f}%)"
    )
    print(
        f"  dsr                  = {gate['dsr']:.6f}  "
        f"(core >= {GATE_DSR} / alt >= {GATE_DSR_ALT})"
    )
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    out = {
        "symbol": SYMBOL,
        "rank": "rank5_adx_conditioning",
        "adx_threshold": adx_threshold,
        "adx_period": ADX_PERIOD,
        "champion_params": {
            "fast": CHAMPION_FAST,
            "slow": CHAMPION_SLOW,
            "atr_trail_mult": CHAMPION_ATR,
            "adx_threshold": adx_threshold,
            "adx_period": ADX_PERIOD,
        },
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "total_oos_trades": gate["total_oos_trades"],
            "sample_adequate": gate["sample_adequate"],
            "win_rate_ci_lower": gate["win_rate_ci_lower"],
        },
        "core_reasons": gate["core_reasons"],
        "alt_reasons": gate["alt_reasons"],
        "windows": window_records,
    }

    fname = f"MGC_trend_rank5_{label}.json"
    out_path = OUTPUT_DIR / fname
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[MGC-R5] Written: {out_path}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="MGC ADX Trend Rank5 canonical validation")
    parser.add_argument(
        "--adx-threshold",
        type=float,
        default=18.0,
        help="ADX threshold to test (default: 18.0 per discovery result)",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Run only adx_threshold=None baseline (reproduce bare rank4 single-combo)",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Run both baseline (no ADX) and ADX-conditioned and print comparison",
    )
    args = parser.parse_args()

    if args.baseline_only:
        run_wfo(adx_threshold=None)
    elif args.both:
        print("\n[Step 1/2] Baseline -- no ADX filter")
        baseline = run_wfo(adx_threshold=None)
        print("\n\n[Step 2/2] ADX-conditioned -- threshold=", args.adx_threshold)
        adx_result = run_wfo(adx_threshold=args.adx_threshold)

        if baseline and adx_result:
            bg = baseline.get("gate_v2_metrics", {})
            ag = adx_result.get("gate_v2_metrics", {})
            print(f"\n{'=' * 70}")
            print("=== COMPARISON: ADX vs BASELINE ===")
            print(f"  {'Metric':<25} {'Baseline (no ADX)':<22} {'ADX=%s' % args.adx_threshold}")
            print(f"  {'-' * 65}")
            metrics = [
                ("verdict", "verdict", "verdict"),
                ("passed_via", "passed_via", "passed_via"),
                ("pf_ci_lower", None, None),
                ("mc_95th_dd_pct", None, None),
                ("dsr", None, None),
                ("total_oos_trades", None, None),
                ("wfo_consistency", None, None),
                ("fixed_params_min_pf", None, None),
            ]
            for row in metrics:
                m = row[0]
                bv = baseline.get(m) if row[1] is None else baseline.get(m)
                av = adx_result.get(m) if row[2] is None else adx_result.get(m)
                if bv is None:
                    bv = bg.get(m)
                    av = ag.get(m)
                print(f"  {m:<25} {str(bv):<22} {av}")
            print(f"{'=' * 70}")
    else:
        run_wfo(adx_threshold=args.adx_threshold)


if __name__ == "__main__":
    main()
