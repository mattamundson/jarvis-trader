#!/usr/bin/env python
"""
Index Breakout Gate v2 — Donchian channel breakout on an equity-index micro.

Companion to the locked spec at docs/strategies/index_breakout_spec.md and the
four-gate MCPT path in backtest/run_mcpt.py (--strategy breakout). Where run_mcpt
answers "is this edge distinguishable from data-mining noise?", this harness
answers "does it clear the gate-v2 CORE/ALT promotion bar after costs?".

Hypothesis: a close beyond the prior N-bar Donchian channel marks a range
expansion that continues far enough, often enough, to beat an ATR stop AND
realistic costs. The nearest analog already FAILED here (MNQ breakout: 55 trades,
0 wins, 2026-05-06/07; M2K Donchian rank1 FAIL 2026-05-24) — this re-tests it
honestly against that benchmark. Default symbol MNQ; parameterize with --symbol.

Method (mirrors backtest/run_m2k_donchian_rank1.py — the established gate-v2
template — swapping generate_donchian_signals for generate_donchian_breakout_signals):
  - Grid: DONCHIAN_PERIODS x STOP_ATR_MULTS (6 combos; deliberately small so the
    Deflated-Sharpe n_trials penalty stays honest). Regime/volume filters OFF —
    baseline first, per the locked spec.
  - Walk-forward: 6mo train, 3mo test, 3mo step.
  - Gate v2 CORE: pf_ci_lower>=1.10, p_edge>=0.95, mc_95th_dd<=5%, dsr>=0.10
  - Gate v2 ALT:  dsr>=0.30, wfo in [MODERATE, STRONG], fixed_params_min_pf>=1.2,
                  cost_survives>=realistic, mc_95th_dd<=7%
  - Trade-count floor: >=100 total OOS trades (locked-spec gate). Below the floor
    the verdict is forced to FAIL regardless of CORE/ALT — small-sample PF is a
    coin flip and must not be promoted.

Cost model, next-bar-open fill, and ATR sizing come from the production
Backtester — nothing here re-implements execution. Diagnostic only; no
engine/config.py, engine/risk/, or kill-switch code is touched.

Writes: engine/data/gate_v2_verdicts/{SYMBOL}_breakout_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_index_breakout_gate_v2.py --symbol MNQ
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from dataclasses import dataclass
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

CAPITAL = 50_000.0

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

# Locked grid — see docs/strategies/index_breakout_spec.md. Kept to 6 combos so
# n_trials fed to Deflated Sharpe is honest and multiple-testing stays controlled.
DONCHIAN_PERIODS = [15, 20, 25]
STOP_ATR_MULTS = [1.5, 2.0]

MIN_OOS_TRADES_PER_WINDOW = 1
#: Locked-spec promotion floor: below this many total OOS trades, PF is a coin
#: flip and the candidate is forced to FAIL even if CORE/ALT pass.
MIN_TOTAL_OOS_TRADES = 100

# Per-symbol: ratios (0.5x/1.0x/2.0x/4.0x) scale off THIS symbol's own base
# commission (cfg.commission, resolved in _resolve_cfg from contract_specs.py)
# rather than a flat MES-based literal (found 2026-07-10 -- _resolve_cfg
# already resolved the primary commission per-symbol, but the cost-sweep
# tiers below did not, so `--symbol MGC`/`--symbol MCL` would cost-sweep at
# the wrong tier).
def _cost_sweep_tiers_for(cfg: "BreakoutCfg") -> dict:
    base_commission = cfg.commission
    return {
        "optimistic": {"commission": round(base_commission * 0.5, 4), "slippage_ticks": 0.5},
        "realistic": {"commission": round(base_commission * 1.0, 4), "slippage_ticks": 1.0},
        "pessimistic": {"commission": round(base_commission * 2.0, 4), "slippage_ticks": 2.0},
        "catastrophic": {"commission": round(base_commission * 4.0, 4), "slippage_ticks": 3.0},
    }


@dataclass(frozen=True)
class BreakoutCfg:
    """Per-run configuration resolved from the contract spec at startup."""

    symbol: str
    multiplier: float
    tick_size: float
    commission: float
    slippage_ticks: float


def _resolve_cfg(symbol: str) -> BreakoutCfg:
    from backtest.contract_specs import CONTRACT_SPECS

    spec = CONTRACT_SPECS.get(symbol.upper())
    if spec is None:
        raise SystemExit(
            f"No contract spec for {symbol!r}. Known: {sorted(CONTRACT_SPECS)}. "
            "Nikkei has no feed/spec in this repo — see docs/strategies/index_breakout_spec.md."
        )
    return BreakoutCfg(
        symbol=symbol.upper(),
        multiplier=spec.multiplier,
        tick_size=spec.tick_size,
        commission=spec.commission,
        slippage_ticks=float(spec.slippage_ticks),
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data(cfg: BreakoutCfg, data_dir: Path) -> pd.DataFrame:
    from backtest._gate_v2_helpers import _find_latest_cache

    data_file = _find_latest_cache(data_dir, cfg.symbol)
    print(f"[{cfg.symbol}] Selected {data_file.name}")
    df = pd.read_csv(data_file)
    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing columns: {missing}")
    print(f"[{cfg.symbol}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# Window generation
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
# Signal + backtest
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    cfg: BreakoutCfg,
    df: pd.DataFrame,
    donchian_period: int,
    stop_atr_mult: float,
    commission: float | None = None,
    slippage_ticks: float | None = None,
) -> object:
    from backtest.backtester import Backtester
    from backtest.breakout_signals import generate_donchian_breakout_signals

    df_sig = generate_donchian_breakout_signals(
        df,
        donchian_period=donchian_period,
        vol_ma_period=20,
        vol_mult=0.0,  # volume filter OFF — baseline first (locked spec)
        stop_atr_mult=stop_atr_mult,
        ema_trend_period=0,  # regime gates OFF — separate locked sweep
        atr_regime_mult=0.0,
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=cfg.commission if commission is None else commission,
        slippage_ticks=cfg.slippage_ticks if slippage_ticks is None else slippage_ticks,
    )
    return bt.run(df_sig, symbol=cfg.symbol, multiplier=cfg.multiplier)


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def _best_is_params(
    cfg: BreakoutCfg,
    df_train: pd.DataFrame,
    grid: list[tuple],
) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None

    for period, stop in grid:
        try:
            result = _run_signals_and_backtest(cfg, df_train, period, stop)
        except Exception as exc:
            print(f"    [WARN] IS error period={period} stop={stop}: {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"donchian_period": period, "stop_atr_mult": stop}
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
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


def _run_fixed_params_sweep(cfg: BreakoutCfg, df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for period, stop in grid:
        try:
            result = _run_signals_and_backtest(cfg, df, period, stop)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "donchian_period": period,
                        "stop_atr_mult": stop,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    period={period:2d} stop={stop:.1f}: "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    period={period:2d} stop={stop:.1f}: "
                    f"SKIP ({result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error period={period} stop={stop}: {exc}")

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


def _run_cost_sweep(cfg: BreakoutCfg, df: pd.DataFrame, champion: dict) -> dict:
    results = {}
    last_surviving = None
    cost_tiers = _cost_sweep_tiers_for(cfg)
    for tier in COST_TIER_ORDER:
        costs = cost_tiers[tier]
        try:
            result = _run_signals_and_backtest(
                cfg,
                df,
                donchian_period=champion["donchian_period"],
                stop_atr_mult=champion["stop_atr_mult"],
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
    cost_passes = cost_tier_idx >= COST_TIER_ORDER.index("realistic")

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

    # Locked-spec trade-count floor: a too-small sample is forced to FAIL even if
    # CORE/ALT statistics pass — promoting a coin flip is the cardinal sin here.
    trade_floor_ok = all_trades >= MIN_TOTAL_OOS_TRADES

    if not trade_floor_ok:
        verdict, passed_via = "FAIL", None
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
        "trade_floor_ok": trade_floor_ok,
        "min_total_oos_trades": MIN_TOTAL_OOS_TRADES,
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


def run_wfo(cfg: BreakoutCfg) -> dict:
    data_dir = engine_root / "backtest" / "cache"
    df = _load_data(cfg, data_dir)

    windows = _generate_windows(df)
    if not windows:
        print(f"[{cfg.symbol}-BRK-R1] ERROR: not enough data to form windows.")
        return {}

    grid = list(itertools.product(DONCHIAN_PERIODS, STOP_ATR_MULTS))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print(f"=== {cfg.symbol} BREAKOUT RANK 1 — DONCHIAN CHANNEL (LONG + SHORT) ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo "
        f"| Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  donchian_period: {DONCHIAN_PERIODS}")
    print(f"  stop_atr_mult:   {STOP_ATR_MULTS}")
    print(f"  mult ${cfg.multiplier:,.1f}/pt | tick {cfg.tick_size} | comm ${cfg.commission}/leg "
          f"| slip {cfg.slippage_ticks}t")
    print("Benchmark: MNQ breakout FAIL (55 trades 0 wins); M2K Donchian rank1 FAIL")
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

        best_params, is_result = _best_is_params(cfg, df_train, grid)

        if best_params is None:
            print(f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)")
            continue

        print(
            f"  Best IS: period={best_params['donchian_period']} "
            f"stop={best_params['stop_atr_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                cfg,
                df_test,
                donchian_period=best_params["donchian_period"],
                stop_atr_mult=best_params["stop_atr_mult"],
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
                "best_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print(f"\n[{cfg.symbol}-BRK-R1] No OOS results — WFO aborted.")
        return {}

    print(f"\n[{cfg.symbol}-BRK-R1] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(cfg, df, grid)
    print(
        f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    param_votes = Counter(
        (r["best_params"]["donchian_period"], r["best_params"]["stop_atr_mult"])
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (20, 2.0)
    champion = {"donchian_period": most_selected[0], "stop_atr_mult": most_selected[1]}
    print(
        f"\n[{cfg.symbol}-BRK-R1] Cost sweep (champion: period={champion['donchian_period']} "
        f"stop={champion['stop_atr_mult']})..."
    )
    cost_sweep_metrics = _run_cost_sweep(cfg, df, champion)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  p_edge               = {gate['p_edge']:.4f}")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%")
    print(f"  dsr                  = {gate['dsr']:.6f}")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}")
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  trade_floor_ok       = {gate['trade_floor_ok']} "
        f"({gate['total_oos_trades']} / {MIN_TOTAL_OOS_TRADES} min OOS trades)"
    )
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades "
        f"/ {gate['n_oos_windows']} total"
    )
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / f"{cfg.symbol}_breakout_rank1.json"

    verdict_doc = {
        "symbol": cfg.symbol,
        "family": "breakout",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "trade_floor_ok": gate["trade_floor_ok"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "champion_params": champion,
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
            "min_total_oos_trades": MIN_TOTAL_OOS_TRADES,
            "donchian_periods": DONCHIAN_PERIODS,
            "stop_atr_mults": STOP_ATR_MULTS,
            "n_combos": n_combos,
        },
        "lineage": {
            "benchmark": "MNQ_breakout / M2K_donchian_rank1",
            "benchmark_verdict": "FAIL",
            "hypothesis": "Donchian N-bar breakout on an index micro — nearest analog "
            "(MNQ breakout, M2K Donchian) already FAILED; re-testing honestly against that "
            "benchmark with the locked spec (baseline, no regime/volume filters).",
            "spec": "docs/strategies/index_breakout_spec.md",
        },
        "windows": window_records,
    }

    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    verdict_doc = _ip(verdict_doc, df=df)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[{cfg.symbol}-BRK-R1] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbol",
        default="MNQ",
        help="index micro to validate (default: MNQ — the nearest Nikkei analog with a feed)",
    )
    args = parser.parse_args()

    cfg = _resolve_cfg(args.symbol)
    verdict = run_wfo(cfg)
    if not verdict:
        print(f"[{cfg.symbol}-BRK-R1] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})
    p = gate.get("p_edge", "?")

    if final == "PASS" and passed_via == "core":
        print(f"\n[PASS-CORE] {cfg.symbol} breakout rank 1 PASSES gate v2 (CORE). p_edge={p}")
    elif final == "PASS" and passed_via == "alt":
        print(f"\n[PASS-ALT] {cfg.symbol} breakout rank 1 PASSES gate v2 (ALT). p_edge={p}")
    else:
        reason = "trade-count floor" if not verdict.get("trade_floor_ok", True) else "gate v2"
        print(f"\n[FAIL] {cfg.symbol} breakout rank 1 FAILS {reason}. p_edge={p}")
        wfo = gate.get("wfo_consistency", "?")
        fmin = gate.get("fixed_params_min_pf", "?")
        print(f"  wfo_consistency={wfo}  fixed_params_min_pf={fmin}  "
              f"total_oos_trades={verdict.get('wfo_config', {}).get('total_oos_trades', '?')}")

    print(f"  Champion params: {verdict.get('champion_params')}")


if __name__ == "__main__":
    main()
