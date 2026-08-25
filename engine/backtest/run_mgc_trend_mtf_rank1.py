#!/usr/bin/env python
"""
MGC SMA-trend rank-1 backtest with multi-timeframe (MTF) daily-regime filter.

Hypothesis: the established MGC Rank-4 SMA-trend edge can be improved by
adding a daily-timeframe regime filter.  Trades are only taken on 1h bars
when the PREVIOUS calendar day's close was above its 50-day SMA (bull regime).
The shift(1) is mandatory -- without it the daily SMA computed on day D would
incorporate the same close that determines the regime, creating lookahead.

Two variants are evaluated side-by-side against gate v2:

  BASELINE  -- raw generate_sma_trend_signals, no MTF filter (fast=50, slow=120,
               atr_trail_mult=2.0 -- the MGC Rank-4 champion parameters).
  MTF       -- same signals; ENTRY_NOW suppressed when daily regime is False or NaN.
               Exit signals are never suppressed (a bear-day stop-out must still fire).

Output
------
  engine/data/gate_v2_verdicts/MGC_trend_baseline.json
  engine/data/gate_v2_verdicts/MGC_trend_mtf.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mgc_trend_mtf_rank1.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path bootstrap -- must come before any local imports
# ---------------------------------------------------------------------------
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
    MIN_OOS_TRADES_TOTAL,
    _find_latest_cache,
    sample_adequacy_enforced,
)
from backtest._gate_v2_helpers import (  # noqa: E402
    bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower,
)
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MGC"
CAPITAL = 50_000.0

# WFO config -- mirror run_trend_diversifier.py IS/OOS/Step months
IS_MONTHS = 12
OOS_MONTHS = 3
STEP_MONTHS = 3

# MGC Rank-4 champion parameters
FAST = 50
SLOW = 120
ATR_TRAIL_MULT = 2.0

# Daily regime SMA period
DAILY_REGIME_PERIOD = 50

MIN_OOS_TRADES_TOTAL_LOCAL = MIN_OOS_TRADES_TOTAL  # 30
MIN_OOS_TRADES_PER_WINDOW = 1


# ---------------------------------------------------------------------------
# Contract spec (inline -- do not import contract_specs to stay self-contained
# for the MTF-specific logic; multiplier/tick/commission match contract_specs.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunConfig:
    """Everything the runner needs for a single variant."""

    symbol: str
    multiplier: float
    tick_size: float
    commission: float
    slippage_ticks: float
    capital: float
    variant: str = "baseline"  # "baseline" or "mtf"
    fast: int = FAST
    slow: int = SLOW
    atr_trail_mult: float = ATR_TRAIL_MULT


def _mgc_config(variant: str = "baseline") -> RunConfig:
    return RunConfig(
        symbol=SYMBOL,
        multiplier=10.0,       # MGC: $10/point (micro gold)
        tick_size=0.10,        # $0.10 minimum increment
        commission=0.85,       # IB tier-1 per leg
        slippage_ticks=1.0,
        capital=CAPITAL,
        variant=variant,
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _find_data_file() -> Path | None:
    """Locate the latest MGC 1h cache. Tries worktree cache first, then main."""
    local_cache = engine_root / "backtest" / "cache"
    pattern = f"{SYMBOL}_*_1h.csv"

    # 2026-08-19 forced DEEP cache (12y, verified clean). The completeness
    # checker demotes to shallow because the 08-18 file is truncated.
    _deep = [p for p in local_cache.glob("MGC_2015-01-01_2026-08-16_1h.csv")]
    if _deep:
        return _deep[0]

    if local_cache.exists() and list(local_cache.glob(pattern)):
        return _find_latest_cache(local_cache, SYMBOL)

    # Worktrees live at <repo>/.claude/worktrees/<name>/ -- repo root is 4 up.
    repo_root = engine_root.parent.parent.parent.parent
    main_cache = repo_root / "engine" / "backtest" / "cache"
    if main_cache.exists() and list(main_cache.glob(pattern)):
        print(f"[{SYMBOL}] Using main checkout cache: {main_cache}")
        return _find_latest_cache(main_cache, SYMBOL)

    return None


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


# ---------------------------------------------------------------------------
# Daily regime computation (no-lookahead)
# ---------------------------------------------------------------------------

def build_daily_regime(df: pd.DataFrame) -> pd.Series:
    """Return a boolean Series indexed like df indicating bull regime.

    A bar on day D is bull when the PREVIOUS day (D-1) closed above its
    50-day SMA.  This mandatory shift(1) prevents lookahead: the daily SMA
    on day D is computed only after day D's session ends, so it cannot be
    used to filter trades taken during day D.

    Parameters
    ----------
    df:
        Hourly DataFrame with a UTC DatetimeIndex.

    Returns
    -------
    pd.Series[bool]
        Same index as df.  True = bull (previous day above daily SMA50),
        False = bear or insufficient history.  NaN positions are treated as
        False (non-bull) by the filter.
    """
    # Resample to daily using close price; ensure UTC-aware index
    if df.index.tz is None:
        daily_close = df["close"].resample("1D").last().dropna()
    else:
        daily_close = df["close"].resample("1D").last().dropna()

    daily_sma50 = daily_close.rolling(DAILY_REGIME_PERIOD).mean()
    daily_regime_bull = daily_close > daily_sma50  # bool, NaN where SMA not ready

    # Shift by 1 day -- no lookahead
    daily_regime_bull_shifted = daily_regime_bull.shift(1)

    # Build a date -> bool mapping (normalize to date for the lookup)
    # daily_regime_bull_shifted has a DatetimeIndex; normalize to midnight
    date_to_regime = pd.Series(
        daily_regime_bull_shifted.values,
        index=daily_regime_bull_shifted.index.normalize(),
    )

    # Map each 1h bar's date onto the daily regime (forward-fill NaN days,
    # e.g. weekends -- safe because weekend bars are absent from futures data)
    bar_dates = df.index.normalize()
    mapped = date_to_regime.reindex(bar_dates, method=None)
    mapped.index = df.index

    # NaN (insufficient daily history) -> False (non-bull)
    return mapped.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# MTF signal filter
# ---------------------------------------------------------------------------

def apply_mtf_regime_filter(df_sig: pd.DataFrame, daily_regime: pd.Series) -> pd.DataFrame:
    """Suppress ENTRY_NOW on bear-regime bars; preserve all EXIT signals.

    Parameters
    ----------
    df_sig:
        Output of generate_sma_trend_signals (has entry_signal / exit_signal cols).
    daily_regime:
        Bool Series with same index as df_sig (True = bull).

    Returns
    -------
    A copy of df_sig with entry_signal overwritten to NO_TRADE where regime is False.
    """
    df_out = df_sig.copy()
    bear_mask = ~daily_regime.reindex(df_out.index).fillna(False).astype(bool)
    df_out.loc[bear_mask, "entry_signal"] = "NO_TRADE"
    return df_out


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------

def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start = df.index.min()
    data_end = df.index.max()
    windows: list[dict] = []
    cursor = data_start
    wnum = 1
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=IS_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=OOS_MONTHS)
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
# Backtester helpers
# ---------------------------------------------------------------------------

def _run_signals_and_backtest(
    cfg: RunConfig,
    df: pd.DataFrame,
    variant: str = "baseline",
    daily_regime: pd.Series | None = None,
    commission: float | None = None,
    slippage_ticks: float | None = None,
) -> object:
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=cfg.fast,
        slow=cfg.slow,
        atr_trail_mult=cfg.atr_trail_mult,
    )

    if variant == "mtf" and daily_regime is not None:
        df_sig = apply_mtf_regime_filter(df_sig, daily_regime)

    bt = Backtester(
        initial_capital=cfg.capital,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=cfg.commission if commission is None else commission,
        slippage_ticks=cfg.slippage_ticks if slippage_ticks is None else slippage_ticks,
    )
    return bt.run(df_sig, symbol=cfg.symbol, multiplier=cfg.multiplier)


def _cost_tiers(cfg: RunConfig) -> dict:
    base = float(cfg.slippage_ticks)
    return {
        "optimistic": {"commission": round(cfg.commission * 0.5, 4), "slippage_ticks": base},
        "realistic": {"commission": round(cfg.commission, 4), "slippage_ticks": base},
        "pessimistic": {"commission": round(cfg.commission * 2.0, 4), "slippage_ticks": base + 1.0},
        "catastrophic": {"commission": round(cfg.commission * 4.0, 4), "slippage_ticks": base + 2.0},
    }


def _run_fixed_params_sweep(
    cfg: RunConfig,
    df: pd.DataFrame,
    variant: str,
    daily_regime: pd.Series | None,
) -> dict:
    result = None
    try:
        result = _run_signals_and_backtest(cfg, df, variant=variant, daily_regime=daily_regime)
    except Exception as exc:
        print(f"  [WARN] fixed-params sweep error: {exc}")
    if result is None or result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": [],
        }
    pf = result.profit_factor
    return {
        "fixed_params_min_pf": round(float(pf), 4),
        "fixed_params_mean_pf": round(float(pf), 4),
        "fixed_params_max_pf": round(float(pf), 4),
        "n_combos_with_trades": 1,
        "combo_results": [
            {
                "fast": cfg.fast,
                "slow": cfg.slow,
                "atr_trail_mult": cfg.atr_trail_mult,
                "pf": round(pf, 4),
                "trades": result.total_trades,
            }
        ],
    }


def _run_cost_sweep(
    cfg: RunConfig,
    df: pd.DataFrame,
    variant: str,
    daily_regime: pd.Series | None,
) -> dict:
    tiers = _cost_tiers(cfg)
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = tiers[tier]
        try:
            result = _run_signals_and_backtest(
                cfg,
                df,
                variant=variant,
                daily_regime=daily_regime,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
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
# Gate v2 evaluation (shared with run_trend_diversifier pattern)
# ---------------------------------------------------------------------------

def _compute_gate_v2(
    cfg: RunConfig,
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest._gate_v2_trade_metrics import (
        trade_level_dsr,
        trade_level_mc_95th_dd,
        trade_level_win_rate_ci_lower,
    )

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL_LOCAL

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=cfg.capital)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=cfg.capital)
    win_rate_ci_lower = trade_level_win_rate_ci_lower(oos_results)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

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

    core_reasons = [
        f"{'FAIL ' if pf_ci_lower < GATE_PF_CI_LOWER else ''}mbb_pf_ci_lower={pf_ci_lower:.4f} >= {GATE_PF_CI_LOWER}",
        f"{'FAIL ' if p_edge < GATE_P_EDGE else ''}p_positive_edge={p_edge:.4f} >= {GATE_P_EDGE}",
        f"mc_95th_dd_pct={mc_95th_dd * 100:.4f} {'<=' if mc_95th_dd <= GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE * 100:.1f}",
        f"dsr={dsr:.6f} >= {GATE_DSR} (not selection-bias)",
    ]
    alt_reasons = [
        f"{'FAIL ' if dsr < GATE_DSR_ALT else ''}dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)",
        f"{'FAIL ' if wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES else ''}rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}",
        f"{'FAIL ' if fixed_params_min_pf < GATE_FIXED_PARAMS_MIN_PF else ''}fixed_params_min_pf={fixed_params_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}",
        f"{'FAIL ' if not cost_passes else ''}cost_survives_through={cost_survives_through} >= realistic",
        f"{'FAIL ' if mc_95th_dd > GATE_MC_DD_ALT else ''}mc_95th_dd_pct={mc_95th_dd * 100:.4f} <= {GATE_MC_DD_ALT * 100:.1f} (alt ceiling)",
    ]
    n_core_passed = sum(1 for r in core_reasons if not r.startswith("FAIL"))
    n_alt_passed = sum(1 for r in alt_reasons if not r.startswith("FAIL"))

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
        "n_core_passed": n_core_passed,
        "n_alt_passed": n_alt_passed,
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
        "min_oos_trades_total": MIN_OOS_TRADES_TOTAL_LOCAL,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------

def run_wfo(cfg: RunConfig, df: pd.DataFrame) -> dict:
    """Run the full WFO + gate-v2 for one variant. Returns verdict dict."""
    windows = _generate_windows(df)
    if not windows:
        print(f"[{cfg.symbol}/{cfg.variant}] ERROR: not enough data to form WFO windows.")
        return {}

    # Build daily regime once over the full dataset (shift(1) inside)
    daily_regime_full = build_daily_regime(df) if cfg.variant == "mtf" else None

    n_combos = 1  # fixed single set of champion params
    print(f"\n{'=' * 70}")
    print(f"=== {cfg.symbol} TREND {cfg.variant.upper()} -- GATE V2 VALIDATION ===")
    print(
        f"Windows: {len(windows)} | IS {IS_MONTHS}mo / OOS {OOS_MONTHS}mo / Step {STEP_MONTHS}mo"
    )
    print(f"Params: fast={cfg.fast}, slow={cfg.slow}, atr_trail={cfg.atr_trail_mult}")
    if cfg.variant == "mtf":
        print(f"MTF filter: daily SMA{DAILY_REGIME_PERIOD} regime (shift=1 day, no lookahead)")
    print("NOTE: VALIDATION ONLY -- no live routing change without Amo authorization.")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []
    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        regime_slice = None
        if daily_regime_full is not None:
            regime_slice = daily_regime_full.reindex(df_test.index)

        try:
            oos_result = _run_signals_and_backtest(
                cfg,
                df_test,
                variant=cfg.variant,
                daily_regime=regime_slice,
            )
        except Exception as exc:
            print(f"  [SKIP] window {win['window_num']} OOS error: {exc}")
            continue

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": win["window_num"],
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print(f"\n[{cfg.symbol}/{cfg.variant}] No OOS results -- WFO aborted.")
        return {}

    all_trades = sum(r.total_trades for r in oos_results)
    print(f"\n  OOS windows: {len(oos_results)} | Total OOS trades: {all_trades}")

    # INSUFFICIENT_SAMPLE short-circuit before heavy metrics
    if all_trades < MIN_OOS_TRADES_TOTAL_LOCAL:
        print(
            f"  [INSUFFICIENT_SAMPLE] {all_trades} OOS trades < {MIN_OOS_TRADES_TOTAL_LOCAL} floor"
        )
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        return {
            "symbol": cfg.symbol,
            "variant": cfg.variant,
            "verdict": "INSUFFICIENT_SAMPLE",
            "passed_via": None,
            "pf_ci_lower": 0.0,
            "p_edge": 0.0,
            "mc_95th_dd": 1.0,
            "mc_95th_dd_pct": 100.0,
            "dsr": 0.0,
            "wfo_consistency": "WEAK",
            "total_oos_trades": all_trades,
            "min_oos_trades_total": MIN_OOS_TRADES_TOTAL_LOCAL,
            "sample_adequate": False,
            "n_oos_windows": len(oos_results),
            "created_at": now_iso,
            "windows": window_records,
        }

    fixed_params_metrics = _run_fixed_params_sweep(cfg, df, cfg.variant, daily_regime_full)
    cost_sweep_metrics = _run_cost_sweep(cfg, df, cfg.variant, daily_regime_full)
    gate = _compute_gate_v2(cfg, oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(
        f"\n=== GATE v2 VERDICT ({cfg.variant}): {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ==="
    )
    print(
        f"  pf_ci_lower={gate['pf_ci_lower']:.4f}  p_edge={gate['p_edge']:.4f}  "
        f"dsr={gate['dsr']:.4f}  mc_dd={gate['mc_95th_dd_pct']:.2f}%  "
        f"oos_trades={gate['total_oos_trades']}"
    )

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": cfg.symbol,
        "variant": cfg.variant,
        "family": "trend",
        "hypothesis": (
            "MGC SMA-trend with daily-regime MTF filter (shift=1 day, no lookahead). "
            "VALIDATION ONLY."
        ),
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": now_iso,
        "gate_v2": {
            "verdict": gate["verdict"],
            "passed_via": gate["passed_via"],
            "core_verdict": gate["core_verdict"],
            "alt_verdict": gate["alt_verdict"],
            "n_core_passed": gate["n_core_passed"],
            "n_core_criteria": 4,
            "n_alt_passed": gate["n_alt_passed"],
            "n_alt_criteria": 5,
            "core_reasons": gate["core_reasons"],
            "alt_reasons": gate["alt_reasons"],
            "reasons": gate["reasons"],
        },
        "wfo_config": {
            "is_months": IS_MONTHS,
            "oos_months": OOS_MONTHS,
            "step_months": STEP_MONTHS,
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
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
            "total_oos_trades": gate["total_oos_trades"],
            "min_oos_trades_total": gate["min_oos_trades_total"],
            "sample_adequate": gate["sample_adequate"],
            "win_rate_ci_lower": gate["win_rate_ci_lower"],
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr_core": GATE_DSR,
            "dsr_alt": GATE_DSR_ALT,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
        },
        "champion_params": {
            "fast": cfg.fast,
            "slow": cfg.slow,
            "atr_trail_mult": cfg.atr_trail_mult,
            "daily_regime_sma": DAILY_REGIME_PERIOD if cfg.variant == "mtf" else None,
        },
        "windows": window_records,
        "contract_spec": {
            "symbol": cfg.symbol,
            "multiplier": cfg.multiplier,
            "tick_size": cfg.tick_size,
            "commission": cfg.commission,
            "slippage_ticks": cfg.slippage_ticks,
            "capital": cfg.capital,
        },
    }
    return verdict_doc


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    data_file = _find_data_file()
    if data_file is None:
        print(
            f"\n[{SYMBOL}] AWAITING DATA PULL -- no {SYMBOL}_*_1h.csv found in cache.\n"
            "  Run an IB Gateway 1h history pull for MGC, then re-run this script.\n"
        )
        sys.exit(3)

    print(f"[{SYMBOL}] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[{SYMBOL}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for variant in ("baseline", "mtf"):
        cfg = _mgc_config(variant=variant)
        verdict = run_wfo(cfg, df)
        results[variant] = verdict
        if verdict:
            fname = f"MGC_trend_{variant}.json"
            out_path = verdicts_dir / fname
            out_path.write_text(json.dumps(verdict, indent=2, default=str))
            print(f"[{SYMBOL}/{variant}] Verdict written -> {out_path}")

    # Side-by-side summary table
    print(f"\n{'=' * 70}")
    print("=== SIDE-BY-SIDE COMPARISON ===")
    print(f"{'Metric':<28} {'BASELINE':>14} {'MTF':>14}")
    print("-" * 58)
    metrics = [
        ("verdict", "verdict"),
        ("pf_ci_lower", "gate_v2_metrics.pf_ci_lower"),
        ("p_edge", "gate_v2_metrics.p_edge"),
        ("mc_95th_dd_pct", "gate_v2_metrics.mc_95th_dd_pct"),
        ("dsr", "gate_v2_metrics.dsr"),
        ("n_oos_trades", "gate_v2_metrics.total_oos_trades"),
        ("wfo_consistency", "gate_v2_metrics.wfo_consistency"),
        ("cost_survives_through", "gate_v2_metrics.cost_survives_through"),
    ]
    for label, key_path in metrics:
        keys = key_path.split(".")
        b_val = results.get("baseline", {})
        m_val = results.get("mtf", {})
        for k in keys:
            b_val = b_val.get(k, "N/A") if isinstance(b_val, dict) else b_val
            m_val = m_val.get(k, "N/A") if isinstance(m_val, dict) else m_val
        print(f"  {label:<26} {str(b_val):>14} {str(m_val):>14}")
    print(f"{'=' * 70}")

    b_verdict = results.get("baseline", {}).get("verdict", "N/A")
    m_verdict = results.get("mtf", {}).get("verdict", "N/A")
    if m_verdict == "PASS" and b_verdict != "PASS":
        print("\n[FINDING] MTF filter IMPROVES edge: MTF PASS, baseline FAIL.")
    elif m_verdict == "PASS" and b_verdict == "PASS":
        print("\n[FINDING] Both variants PASS gate v2. Compare metrics for quality.")
    elif m_verdict == "FAIL" and b_verdict == "PASS":
        print("\n[FINDING] MTF filter DEGRADES edge: baseline PASS, MTF FAIL.")
    elif m_verdict == "INSUFFICIENT_SAMPLE":
        print("\n[FINDING] MTF filters too many trades -- INSUFFICIENT_SAMPLE.")
    else:
        print(f"\n[FINDING] baseline={b_verdict}, mtf={m_verdict}.")


if __name__ == "__main__":
    main()
