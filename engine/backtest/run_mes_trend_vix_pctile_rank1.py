#!/usr/bin/env python
"""
MES Trend VIX Percentile-Tier Gate v2 — Rank 1

Hypothesis: Suppressing SMA(60,200) MES golden-cross entries while VIX sits in a
high percentile tier (Crisis / HighVol) concentrates the trend edge the same way
the absolute vix_min/vix_max gate (run_mes_trend_vix_rank1.py) does, but ADAPTS to
volatility-regime drift instead of using fixed VIX prints. A VIX of 22 means
something different in a calm year than a turbulent one; the percentile lens
accounts for that.

Method:
  - SMA trend params FIXED at rank11 champion: fast=60, slow=200, atr_trail_mult=2.0
  - Grid over which percentile TIERS to block (the variable being optimized)
  - Tiers from backtest.vix_percentile_regime (rolling trailing percentile, mid-rank)
  - VIX data via yfinance (^VIX daily close); tiers ffilled to 1h MES bars (point-in-time)
  - Gate v2 ALT/CORE PASS of at least one tier-block combo writes a verdict

Grid (TIER_BLOCK_GRID):
  ()                          -> block nothing (rank11 baseline reproduction)
  ("Crisis",)                 -> block only the top tier
  ("Crisis", "HighVol")       -> block the two highest vol tiers
  ("HighVol",)                -> block the second tier only

Goal: match or beat rank11 baseline (p_edge=0.75 ALT PASS) with an adaptive gate.
  This is a NEW search over 4 combos, so DSR (multiple-testing correction) is gated
  in _compute_gate_v2 per .claude/rules/ml-pitfalls-defense.md.

Writes: engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_trend_vix_pctile_rank1.py

Requires yfinance:
    .venv/Scripts/pip install yfinance
"""
from __future__ import annotations

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

# SMA params FIXED at rank11 champion — not part of the grid
FAST = 60
SLOW = 200
ATR_TRAIL_MULT = 2.0

# Percentile window for the tier classifier (~1y of daily VIX bars).
VIX_REGIME_LOOKBACK = 252

# Tier-block grid — the variable being optimized. Empty tuple = no gate (baseline).
TIER_BLOCK_GRID: list[tuple[str, ...]] = [
    (),
    ("Crisis",),
    ("Crisis", "HighVol"),
    ("HighVol",),
]

MIN_OOS_TRADES_PER_WINDOW = 1

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}


# ---------------------------------------------------------------------------
# Data loading (VIX via yfinance, MES via cache) — mirrors rank1
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
    vix.index = pd.to_datetime(vix.index).normalize()
    print(
        f"[VIX] {len(vix)} bars | {vix.index.min().date()} -> {vix.index.max().date()} "
        f"| current: {vix['close'].iloc[-1]:.2f}"
    )
    return vix[["close"]]


def _load_mes_data(data_dir: Path) -> pd.DataFrame:
    from backtest._gate_v2_helpers import _find_latest_cache

    data_file = _find_latest_cache(data_dir, "MES")
    print(f"[MES] Selected {data_file.name}")
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    print(f"[MES] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# Window generation (identical to rank1)
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
# Signal + backtest (percentile-tier aware)
# ---------------------------------------------------------------------------


def _label(block: tuple[str, ...]) -> str:
    return "none" if not block else "+".join(block)


def _run_signals_and_backtest(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    blocked_tiers: tuple[str, ...],
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
        vix_regime_block=blocked_tiers if blocked_tiers else None,
        vix_regime_lookback=VIX_REGIME_LOOKBACK,
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


def _best_is_block(
    df_train: pd.DataFrame,
    vix_df: pd.DataFrame,
    grid: list[tuple[str, ...]],
) -> tuple[tuple[str, ...] | None, object | None]:
    best_pf = -1.0
    best_block: tuple[str, ...] | None = None
    best_result = None

    for block in grid:
        try:
            result = _run_signals_and_backtest(df_train, vix_df, block)
        except Exception as exc:
            print(f"    [WARN] IS error block={_label(block)}: {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if result.profit_factor > best_pf:
            best_pf = result.profit_factor
            best_block = block
            best_result = result

    return best_block, best_result


# ---------------------------------------------------------------------------
# Gate v2 helpers (reused from rank1's shared modules)
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
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


def _run_fixed_params_sweep(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    grid: list[tuple[str, ...]],
) -> dict:
    """Fixed-params sweep across all tier-block combos on the full dataset."""
    pfs = []
    combo_results = []
    for block in grid:
        try:
            result = _run_signals_and_backtest(df, vix_df, block)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "blocked_tiers": list(block),
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    block=[{_label(block):16s}]: "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    block=[{_label(block):16s}]: SKIP (only {result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error block={_label(block)}: {exc}")

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
    champion_block: tuple[str, ...],
) -> dict:
    results = {}
    last_surviving = None

    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                vix_df,
                champion_block,
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
        print("[MES-VIXPCT-R1] ERROR: not enough data to form windows.")
        return {}

    grid = TIER_BLOCK_GRID
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MES TREND VIX PERCENTILE-TIER RANK 1 ===")
    print(f"SMA fixed: fast={FAST}, slow={SLOW}, atr_trail_mult={ATR_TRAIL_MULT} (rank11 champion)")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | "
        f"Step: {STEP_MONTHS}mo"
    )
    print(f"Tier-block grid ({n_combos} combos, lookback={VIX_REGIME_LOOKBACK}d):")
    for block in grid:
        print(f"  block=[{_label(block)}]")
    print("Rank11 baseline: p_edge=0.75, mc_dd=0.81%, dsr=1.0  (target: match or beat ALT)")
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

        best_block, is_result = _best_is_block(df_train, vix_df, grid)

        if best_block is None:
            print(
                f"  [SKIP] No valid IS block (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)"
            )
            continue

        print(
            f"  Best IS: block=[{_label(best_block)}]  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(df_test, vix_df, best_block)
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
                "best_blocked_tiers": list(best_block),
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("\n[MES-VIXPCT-R1] No OOS results — WFO aborted.")
        return {}

    print(
        f"\n[MES-VIXPCT-R1] Running fixed-params sweep on full dataset ({n_combos} combos)..."
    )
    fixed_params_metrics = _run_fixed_params_sweep(df, vix_df, grid)
    print(
        f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    block_votes = Counter(tuple(r["best_blocked_tiers"]) for r in window_records)
    champion_block = block_votes.most_common(1)[0][0] if block_votes else ("Crisis",)
    print(
        f"\n[MES-VIXPCT-R1] Running cost sweep (champion block=[{_label(champion_block)}])..."
    )
    cost_sweep_metrics = _run_cost_sweep(df, vix_df, champion_block)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

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
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / "
        f"{gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MES_trend_vix_pctile_rank1.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend_vix_pctile",
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
            "note": "Fixed at rank11 champion — percentile tier block is the only variable",
        },
        "champion_blocked_tiers": list(champion_block),
        "vix_regime_lookback": VIX_REGIME_LOOKBACK,
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
            "tier_block_grid": [list(b) for b in grid],
            "n_combos": n_combos,
        },
        "lineage": {
            "baseline": "MES_trend_vix_rank1",
            "baseline_p_edge": 0.75,
            "baseline_verdict": "PASS via alt",
            "hypothesis": "Adaptive VIX percentile-tier block matches/beats the fixed vix_min/vix_max gate",
            "target_improvement": "p_edge >= 0.75 with fewer over-fit DOF (4 combos vs 9)",
        },
        "windows": window_records,
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-VIXPCT-R1] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MES-VIXPCT-R1] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MES Trend VIX Percentile Rank 1 PASSES gate v2 (CORE path).")
        print(f"  p_edge={gate.get('p_edge', '?')} >= {GATE_P_EDGE} — CORE threshold reached!")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MES Trend VIX Percentile Rank 1 PASSES gate v2 (ALT path).")
        print(f"  p_edge={gate.get('p_edge', '?')} (rank11 baseline was 0.75).")
        print("  Adaptive percentile gate matches the fixed-VIX gate with fewer DOF.")
    else:
        print(f"\n[FAIL] MES Trend VIX Percentile Rank 1 FAILS gate v2. p_edge={gate.get('p_edge', '?')}")
        print("  Percentile gate may suppress too many trades — try blocking only Crisis in rank2.")

    print(f"  Champion blocked tiers: {verdict.get('champion_blocked_tiers')}")


if __name__ == "__main__":
    main()
