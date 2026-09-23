#!/usr/bin/env python
"""
MCL / MNQ Trend VIX Percentile-Tier Gate v2 — HALTED-instrument re-diagnosis

Task #5 (session ROI review, 2026-07-01): both MCL and MNQ are HALTED
(`DO_NOT_TRADE_SYMBOLS`, see `engine/CLAUDE.md` "Active Instruments") after their
trend/breakout/ORB/mean-reversion families were exhausted against FIXED VIX
thresholds. The percentile-tier VIX gate shipped for MES (PR #120/#137,
`run_mes_trend_vix_pctile_rank1.py`) is a genuinely untried angle: it adapts to
volatility-REGIME drift instead of a fixed VIX print, which the exhausted MCL/MNQ
hypotheses never tested. This is that same method, generalized by symbol.

Method (identical to the MES rank1 script — see its docstring for the full
rationale): SMA trend params FIXED at each symbol's last-tried champion grid,
grid over which VIX percentile TIERS to block, gate v2 ALT/CORE PASS writes a
verdict. Reuses the same shared primitives (`Backtester`, `generate_sma_trend_signals`,
`backtest._gate_v2_helpers`, `backtest._gate_v2_trade_metrics`,
`backtest._constants`) rather than reimplementing gate math — see
`jarvis-search-discipline`.

Champion params reused from the LAST real attempt on each symbol (not invented):
  - MCL: fast=10, slow=40, atr_trail_mult=1.5
    (`engine/data/gate_v2_verdicts/archive/MCL_trend_hyp_e.json`, FAIL vs fixed VIX)
  - MNQ: fast=25, slow=80, atr_trail_mult=1.5
    (`engine/data/gate_v2_verdicts/archive/MNQ_trend_rank2.json`, FAIL vs fixed VIX)

Data: neither symbol has a native 1h cache (only 15m/5m under `backtest/cache/`).
This resamples the 15m cache to 1h with `resample("1h", label="left", closed="left")`
— label/closed=left means each 1h bar is built ONLY from bars up to and including
that hour, so no look-ahead is introduced (verified: MCL 15m -> 3,344 clean 1h bars
matching the raw file's own span).

IMPORTANT — environment note: this script was authored and its DATA PATH smoke-
tested (cache load + resample + window generation) in a remote sandbox whose
network proxy blocks Yahoo Finance (`^VIX` fetch returns HTTP 403 at the CONNECT
tunnel), so the VIX-DEPENDENT gate math has NOT been run end-to-end here. Run
`--smoke-test` anywhere to verify the data path without network access. Run for
real (no flag) on a machine where `yfinance` can reach Yahoo — do not trust a
verdict produced by fabricated or stubbed VIX data.

Writes: engine/data/gate_v2_verdicts/{SYMBOL}_trend_vix_pctile_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_trend_vix_pctile_gate.py --symbol MCL
    .venv/Scripts/python backtest/run_trend_vix_pctile_gate.py --symbol MNQ
    .venv/Scripts/python backtest/run_trend_vix_pctile_gate.py --symbol MCL --smoke-test

Requires yfinance (skipped in --smoke-test):
    .venv/Scripts/pip install yfinance
"""
from __future__ import annotations

import argparse
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
    _find_latest_cache,
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

# ---------------------------------------------------------------------------
# Per-symbol config — champion params reused from the last real attempt
# (see module docstring for provenance), contract specs from paper_config.py.
# ---------------------------------------------------------------------------

SYMBOL_CONFIGS = {
    "MCL": {
        "fast": 10, "slow": 40, "atr_trail_mult": 1.5,
        "multiplier": 100.0, "tick_size": 0.01,
        "commission": CONTRACT_SPECS["MCL"].commission, "slippage_ticks": 1.0,
        "capital": 10_000.0,
        "cache_suffix": "_15m.csv",  # no native 1h cache -> resample
        "baseline_note": "MCL_trend_hyp_e FAIL vs fixed VIX (WFO=STRONG, mc_dd=0.23%, near-miss on p_edge)",
    },
    "MNQ": {
        "fast": 25, "slow": 80, "atr_trail_mult": 1.5,
        "multiplier": 2.0, "tick_size": 0.25,
        "commission": CONTRACT_SPECS["MNQ"].commission, "slippage_ticks": 1.0,
        "capital": 10_000.0,
        "cache_suffix": "_15m.csv",  # no native 1h cache -> resample
        "baseline_note": "MNQ_trend_rank2 FAIL vs fixed VIX (dsr=0.159, mc_dd=13.46% > 6% core ceiling)",
    },
}

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1
VIX_REGIME_LOOKBACK = 252
MIN_OOS_TRADES_PER_WINDOW = 1

TIER_BLOCK_GRID: list[tuple[str, ...]] = [
    (),
    ("Crisis",),
    ("Crisis", "HighVol"),
    ("HighVol",),
]

# Cost-sweep tiers scale as a ratio of the SYMBOL's own commission (0.5x
# optimistic / 1.0x realistic / 2.0x pessimistic / 4.0x catastrophic --
# established convention elsewhere in this codebase, e.g. MES's 0.31/0.62/
# 1.24/2.48 = 0.5x/1x/2x/4x of MES's 0.62 commission). This script serves
# two symbols (MCL commission=0.85, MNQ commission=0.62) from one cfg dict,
# so the tiers are computed per-symbol from cfg["commission"] rather than
# hardcoded, to avoid silently reusing one symbol's absolute rate for both.
COST_SWEEP_TIER_MULTIPLIERS = {
    "optimistic": 0.5,
    "realistic": 1.0,
    "pessimistic": 2.0,
    "catastrophic": 4.0,
}
COST_SWEEP_SLIPPAGE_TICKS = {
    "optimistic": 1.0,
    "realistic": 2.0,
    "pessimistic": 3.0,
    "catastrophic": 4.0,
}


def _cost_sweep_tiers(base_commission: float) -> dict[str, dict[str, float]]:
    """Build the cost-sweep tier dict for the symbol's own commission rate."""
    return {
        tier: {
            "commission": round(base_commission * mult, 4),
            "slippage_ticks": COST_SWEEP_SLIPPAGE_TICKS[tier],
        }
        for tier, mult in COST_SWEEP_TIER_MULTIPLIERS.items()
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_vix_data(start: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        print("[ERROR] yfinance not installed. Run: .venv/Scripts/pip install yfinance")
        sys.exit(1)

    print(f"[VIX] Downloading ^VIX daily from {start} ...")
    vix = yf.download("^VIX", start=start, progress=False, auto_adjust=True)
    if vix.empty:
        print("[ERROR] yfinance returned empty VIX data (network/proxy issue?).")
        sys.exit(1)

    vix.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in vix.columns]
    vix.index = pd.to_datetime(vix.index).normalize()
    print(
        f"[VIX] {len(vix)} bars | {vix.index.min().date()} -> {vix.index.max().date()} "
        f"| current: {vix['close'].iloc[-1]:.2f}"
    )
    return vix[["close"]]


_RESAMPLE_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def _load_symbol_data(symbol: str, data_dir: Path, cache_suffix: str) -> pd.DataFrame:
    """Load the finest available cache and resample to 1h if needed.

    label="left", closed="left" means each 1h bucket is built only from bars
    timestamped at or after its own start and before the next hour begins --
    no bar from the future leaks into an earlier bucket.
    """
    data_file = _find_latest_cache(data_dir, symbol, suffix=cache_suffix)
    print(f"[{symbol}] Selected {data_file.name}")
    df = pd.read_csv(data_file)
<<<<<<< HEAD
=======
    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(data_file)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    if cache_suffix != "_1h.csv":
        n_before = len(df)
        df = df.resample("1h", label="left", closed="left").agg(_RESAMPLE_AGG).dropna()
        print(f"[{symbol}] Resampled {cache_suffix.strip('_.csv')} -> 1h: {n_before} -> {len(df)} bars")

    print(f"[{symbol}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# Window generation (identical to the MES rank1 script)
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


def _label(block: tuple[str, ...]) -> str:
    return "none" if not block else "+".join(block)


# ---------------------------------------------------------------------------
# Signal + backtest
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    vix_df: pd.DataFrame,
    blocked_tiers: tuple[str, ...],
    cfg: dict,
    commission: float | None = None,
    slippage_ticks: float | None = None,
) -> object:
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=cfg["fast"],
        slow=cfg["slow"],
        atr_trail_mult=cfg["atr_trail_mult"],
        vix_df=vix_df,
        vix_regime_block=blocked_tiers if blocked_tiers else None,
        vix_regime_lookback=VIX_REGIME_LOOKBACK,
    )

    bt = Backtester(
        initial_capital=cfg["capital"],
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=commission if commission is not None else cfg["commission"],
        slippage_ticks=slippage_ticks if slippage_ticks is not None else cfg["slippage_ticks"],
    )
    return bt.run(df_sig, symbol=cfg["_symbol"], multiplier=cfg["multiplier"])


def _best_is_block(
    df_train: pd.DataFrame, vix_df: pd.DataFrame, grid: list[tuple[str, ...]], cfg: dict
) -> tuple[tuple[str, ...] | None, object | None]:
    best_pf = -1.0
    best_block: tuple[str, ...] | None = None
    best_result = None
    for block in grid:
        try:
            result = _run_signals_and_backtest(df_train, vix_df, block, cfg)
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


def _run_fixed_params_sweep(df: pd.DataFrame, vix_df: pd.DataFrame, grid: list[tuple[str, ...]], cfg: dict) -> dict:
    pfs, combo_results = [], []
    for block in grid:
        try:
            result = _run_signals_and_backtest(df, vix_df, block, cfg)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {"blocked_tiers": list(block), "pf": round(result.profit_factor, 4), "trades": result.total_trades}
                )
                print(f"    block=[{_label(block):16s}]: PF={result.profit_factor:.4f}  trades={result.total_trades}")
            else:
                print(f"    block=[{_label(block):16s}]: SKIP (only {result.total_trades} trades)")
        except Exception as exc:
            print(f"  [WARN] fixed-params error block={_label(block)}: {exc}")

    if not pfs:
        return {"fixed_params_min_pf": 0.0, "fixed_params_mean_pf": 0.0, "fixed_params_max_pf": 0.0,
                "n_combos_with_trades": 0, "combo_results": combo_results}
    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combo_results,
    }


def _run_cost_sweep(df: pd.DataFrame, vix_df: pd.DataFrame, champion_block: tuple[str, ...], cfg: dict) -> dict:
    results = {}
    last_surviving = None
    cost_sweep_tiers = _cost_sweep_tiers(cfg["commission"])
    for tier in COST_TIER_ORDER:
        costs = cost_sweep_tiers[tier]
        try:
            result = _run_signals_and_backtest(
                df, vix_df, champion_block, cfg,
                commission=costs["commission"], slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  slip={costs['slippage_ticks']:.1f}t  "
                f"PF={pf:.4f}  trades={result.total_trades}  {'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last_surviving = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last_surviving or "none", "tier_results": results}


def _compute_gate_v2(oos_results: list, n_grid_combos: int, fixed_params_metrics: dict, cost_sweep_metrics: dict, cfg: dict) -> dict:
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=cfg["capital"])

    wfo_consistency = _classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")

    cost_tier_idx = COST_TIER_ORDER.index(cost_survives_through) if cost_survives_through in COST_TIER_ORDER else -1
    cost_realistic_idx = COST_TIER_ORDER.index("realistic")
    cost_passes = cost_tier_idx >= cost_realistic_idx

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    if core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    return {
        "verdict": verdict, "passed_via": passed_via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "pf_ci_lower": round(pf_ci_lower, 4), "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6), "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6), "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results), "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo(symbol: str, smoke_test: bool = False) -> dict:
    if symbol not in SYMBOL_CONFIGS:
        print(f"[ERROR] Unknown symbol {symbol!r}. Supported: {list(SYMBOL_CONFIGS)}")
        sys.exit(1)
    cfg = dict(SYMBOL_CONFIGS[symbol])
    cfg["_symbol"] = symbol

    data_dir = engine_root / "backtest" / "cache"
    df = _load_symbol_data(symbol, data_dir, cfg["cache_suffix"])
    windows = _generate_windows(df)

    if smoke_test:
        print(f"\n[{symbol}-VIXPCT] SMOKE TEST — data path only, no VIX fetch, no backtest run.")
        print(f"  {len(windows)} WFO windows generated from {len(df)} 1h bars.")
        if not windows:
            print("  [FAIL] No windows generated — insufficient data.")
            return {}
        w0, wN = windows[0], windows[-1]
        print(f"  First window: IS {w0['train_start'].date()}->{w0['train_end'].date()}  "
              f"OOS {w0['test_start'].date()}->{w0['test_end'].date()}")
        print(f"  Last  window: IS {wN['train_start'].date()}->{wN['train_end'].date()}  "
              f"OOS {wN['test_start'].date()}->{wN['test_end'].date()}")
        print("  [OK] Data path verified. Re-run WITHOUT --smoke-test on a machine with yfinance access.")
        return {"smoke_test": True, "n_windows": len(windows), "n_bars": len(df)}

    if not windows:
        print(f"[{symbol}-VIXPCT] ERROR: not enough data to form windows.")
        return {}

    vix_df = _load_vix_data(start=str(df.index.min().date()))
    grid = TIER_BLOCK_GRID
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print(f"=== {symbol} TREND VIX PERCENTILE-TIER GATE v2 (HALTED re-diagnosis) ===")
    print(f"SMA fixed: fast={cfg['fast']}, slow={cfg['slow']}, atr_trail_mult={cfg['atr_trail_mult']} "
          f"(last-tried champion — {cfg['baseline_note']})")
    print(f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo")
    print(f"Tier-block grid ({n_combos} combos, lookback={VIX_REGIME_LOOKBACK}d):")
    for block in grid:
        print(f"  block=[{_label(block)}]")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        print(f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
              f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  ({win['n_train']} / {win['n_test']} bars)")

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_block, is_result = _best_is_block(df_train, vix_df, grid, cfg)
        if best_block is None:
            print(f"  [SKIP] No valid IS block (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)")
            continue
        print(f"  Best IS: block=[{_label(best_block)}]  PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}")

        try:
            oos_result = _run_signals_and_backtest(df_test, vix_df, best_block, cfg)
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(f"  OOS:     PF={oos_result.profit_factor:.2f}  DD={oos_result.max_drawdown_pct:.1%}  "
              f"Sharpe={oos_result.sharpe_ratio:.2f}  trades={oos_result.total_trades}")

        oos_results.append(oos_result)
        window_records.append({
            "window": wnum,
            "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
            "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
            "best_blocked_tiers": list(best_block),
            "is_pf": round(is_result.profit_factor, 3), "is_trades": is_result.total_trades,
            "oos_pf": round(oos_result.profit_factor, 3), "oos_dd": round(oos_result.max_drawdown_pct, 4),
            "oos_sharpe": round(oos_result.sharpe_ratio, 3), "oos_trades": oos_result.total_trades,
        })

    if not oos_results:
        print(f"\n[{symbol}-VIXPCT] No OOS results — WFO aborted.")
        return {}

    print(f"\n[{symbol}-VIXPCT] Running fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, vix_df, grid, cfg)
    print(f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})")

    block_votes = Counter(tuple(r["best_blocked_tiers"]) for r in window_records)
    champion_block = block_votes.most_common(1)[0][0] if block_votes else ("Crisis",)
    print(f"\n[{symbol}-VIXPCT] Running cost sweep (champion block=[{_label(champion_block)}])...")
    cost_sweep_metrics = _run_cost_sweep(df, vix_df, champion_block, cfg)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

    gate = _compute_gate_v2(oos_results, n_grid_combos=n_combos, fixed_params_metrics=fixed_params_metrics,
                             cost_sweep_metrics=cost_sweep_metrics, cfg=cfg)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT ({symbol}): {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  p_edge               = {gate['p_edge']:.4f}")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%")
    print(f"  dsr                  = {gate['dsr']:.6f}")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}")
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total")
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / f"{symbol}_trend_vix_pctile_rank1.json"

    verdict_doc = {
        "symbol": symbol, "family": "trend_vix_pctile", "rank": 1,
        "verdict": gate["verdict"], "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"], "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "sma_params": {"fast": cfg["fast"], "slow": cfg["slow"], "atr_trail_mult": cfg["atr_trail_mult"],
                       "note": f"Fixed at last-tried champion ({cfg['baseline_note']}) — percentile tier block is the only variable"},
        "champion_blocked_tiers": list(champion_block),
        "vix_regime_lookback": VIX_REGIME_LOOKBACK,
        "gate_v2_metrics": {k: gate[k] for k in (
            "pf_ci_lower", "p_edge", "mc_95th_dd", "mc_95th_dd_pct", "dsr", "wfo_consistency",
            "fixed_params_min_pf", "fixed_params_mean_pf", "fixed_params_max_pf", "cost_survives_through",
        )},
        "wfo_config": {
            "train_months": TRAIN_MONTHS, "test_months": TEST_MONTHS, "step_months": STEP_MONTHS,
            "n_windows": len(windows), "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "tier_block_grid": [list(b) for b in grid], "n_combos": n_combos,
        },
        "lineage": {
            "baseline": cfg["baseline_note"],
            "hypothesis": "Adaptive VIX percentile-tier block succeeds where the exhausted fixed-VIX "
                          "hypotheses failed, by adapting to volatility-regime drift.",
        },
        "windows": window_records,
    }
<<<<<<< HEAD
=======
    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    verdict_doc = _ip(verdict_doc, df=df)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[{symbol}-VIXPCT] Verdict written -> {verdict_file}")
    return verdict_doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True, choices=sorted(SYMBOL_CONFIGS), help="Instrument to re-diagnose")
    ap.add_argument("--smoke-test", action="store_true",
                    help="Verify the data path (cache load, resample, WFO windows) without fetching VIX or running a backtest")
    args = ap.parse_args()

    verdict = run_wfo(args.symbol, smoke_test=args.smoke_test)
    if not verdict:
        print(f"[{args.symbol}-VIXPCT] No verdict produced — check data/logs above.")
        sys.exit(1)
    if verdict.get("smoke_test"):
        return

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})
    if final == "PASS":
        print(f"\n[PASS-{(passed_via or '?').upper()}] {args.symbol} Trend VIX Percentile Gate PASSES gate v2.")
        print("  This would be the first surface to clear gate v2 since the symbol was HALTED —")
        print("  do NOT flip DO_NOT_TRADE_SYMBOLS without a [safety-review] PR and Tier 3 review.")
    else:
        print(f"\n[FAIL] {args.symbol} Trend VIX Percentile Gate FAILS gate v2. p_edge={gate.get('p_edge', '?')}")
        print(f"  {args.symbol} stays HALTED. This is a real result, not a failure to act on.")
    print(f"  Champion blocked tiers: {verdict.get('champion_blocked_tiers')}")


if __name__ == "__main__":
    main()
