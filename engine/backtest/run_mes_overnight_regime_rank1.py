"""
MES Overnight Carry, REGIME-CONDITIONAL -- gate-v2 walk-forward validation.

Follow-up to run_mes_overnight_rank1.py, which was a near-miss FAIL
(pf_ci_lower 0.9955 vs 1.10): raw overnight carry has a real edge most of the
time but lost OOS consistency on the 2024 equity bear cluster. Hypothesis
(both research streams, 2026-06-17): the overnight equity-carry premium
concentrates in calm/uptrend regimes; selloffs spike volatility, so a
volatility-stress gate that stands aside when trailing realized vol is elevated
should drop the worst sessions and recover consistency.

Two regime axes, gridded jointly:
    filter_len    in [0, 200]          -- SMA trend filter (close > SMA)
    max_rv_ann    in [0, 15, 20, 30]   -- skip entry when 20-bar annualized
                                          realized vol (%) exceeds the threshold
=> 8 combos. (0, 0) reproduces raw overnight carry, so the grid can only help
or no-op relative to the rank1 baseline. The larger grid raises the DSR bar
(deflated Sharpe penalizes for combos tried) -- intentional, honest.

WFO schedule (matches the rank1 runner and other gate-v2 runners):
    Train: 6 months  |  Test: 2 months  |  Step: 1 month

VALIDATION ONLY. A PASS does NOT wire live routing -- that requires Tier-3 /
Amo owner authorization.

Usage (from engine/ directory):
    API_KEY=test-key .venv/Scripts/python backtest/run_mes_overnight_regime_rank1.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
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
from backtest.contract_specs import get_spec  # noqa: E402

SYMBOL = "MES"
TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1

# 2D regime grid.
FILTER_LEN_VALUES: list[int] = [0, 200]
MAX_RV_VALUES: list[float] = [0.0, 15.0, 20.0, 30.0]

MIN_OOS_TRADES_PER_WINDOW = 1


@dataclass(frozen=True)
class RunConfig:
    """Regime-conditional overnight carry runner configuration."""

    symbol: str
    multiplier: float
    tick_size: float
    commission: float
    slippage_ticks: float
    capital: float
    filter_len_values: list[int] = field(default_factory=lambda: list(FILTER_LEN_VALUES))
    max_rv_values: list[float] = field(default_factory=lambda: list(MAX_RV_VALUES))

    @property
    def grid(self) -> list[tuple[int, float]]:
        return [(fl, rv) for fl in self.filter_len_values for rv in self.max_rv_values]


def _make_config(capital: float = 50_000.0) -> RunConfig:
    spec = get_spec(SYMBOL)
    return RunConfig(
        symbol=SYMBOL,
        multiplier=spec.multiplier,
        tick_size=spec.tick_size,
        commission=spec.commission,
        slippage_ticks=float(spec.slippage_ticks),
        capital=capital,
    )


def _cost_tiers(commission: float, slippage_ticks: float) -> dict:
    base = float(slippage_ticks)
    return {
        "optimistic": {"commission": round(commission * 0.5, 4), "slippage_ticks": base},
        "realistic": {"commission": round(commission, 4), "slippage_ticks": base},
        "pessimistic": {"commission": round(commission * 2.0, 4), "slippage_ticks": base + 1.0},
        "catastrophic": {"commission": round(commission * 4.0, 4), "slippage_ticks": base + 2.0},
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    if df[ts_col].dt.tz is None:
        df[ts_col] = df[ts_col].dt.tz_localize("UTC")
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _find_data_file() -> Path | None:
    """Locate the deepest MES 1h cache (most rows), falling back to main checkout."""
    data_dir = engine_root / "backtest" / "cache"
    pattern = f"{SYMBOL}_*_1h.csv"
    if not list(data_dir.glob(pattern)):
        repo_root = engine_root.parent.parent.parent.parent
        main_cache = repo_root / "engine" / "backtest" / "cache"
        if main_cache.exists() and list(main_cache.glob(pattern)):
            data_dir = main_cache
            print(f"[{SYMBOL}] Using main checkout cache: {data_dir}")
    if not list(data_dir.glob(pattern)):
        return None
    return _find_latest_cache(data_dir, SYMBOL)


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
# Signal + backtest execution
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    cfg: RunConfig,
    df: pd.DataFrame,
    filter_len: int,
    max_rv: float,
    commission: float | None = None,
    slippage_ticks: float | None = None,
) -> object:
    from backtest.backtester import Backtester
    from backtest.overnight_signals import generate_overnight_signals

    df_sig = generate_overnight_signals(df, filter_len=filter_len, max_rv_annualized=max_rv)

    bt = Backtester(
        initial_capital=cfg.capital,
        risk_per_trade=0.01,
        max_daily_loss=0.10,
        max_drawdown=0.20,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=cfg.commission if commission is None else commission,
        slippage_ticks=cfg.slippage_ticks if slippage_ticks is None else slippage_ticks,
        eod_close=False,
        use_targets=False,
        fixed_contracts=1,
    )
    return bt.run(df_sig, symbol=cfg.symbol, multiplier=cfg.multiplier)


def _best_is_params(cfg: RunConfig, df_train: pd.DataFrame) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None
    for (filter_len, max_rv) in cfg.grid:
        try:
            result = _run_signals_and_backtest(cfg, df_train, filter_len, max_rv)
        except Exception as exc:
            print(f"    [WARN] IS error (fl={filter_len}, rv={max_rv}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"filter_len": filter_len, "max_rv": max_rv}
            best_result = result
    return best_params, best_result


def _run_fixed_params_sweep(cfg: RunConfig, df: pd.DataFrame) -> dict:
    pfs = []
    combo_results = []
    for (filter_len, max_rv) in cfg.grid:
        try:
            result = _run_signals_and_backtest(cfg, df, filter_len, max_rv)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "filter_len": filter_len,
                        "max_rv": max_rv,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error (fl={filter_len}, rv={max_rv}): {exc}")
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


def _run_cost_sweep(cfg: RunConfig, df: pd.DataFrame, champion_params: dict) -> dict:
    tiers = _cost_tiers(cfg.commission, cfg.slippage_ticks)
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = tiers[tier]
        try:
            result = _run_signals_and_backtest(
                cfg,
                df,
                filter_len=champion_params["filter_len"],
                max_rv=champion_params["max_rv"],
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
# Gate v2 evaluation
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
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

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
        "min_oos_trades_total": MIN_OOS_TRADES_TOTAL,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


def run_wfo(cfg: RunConfig | None = None) -> dict:
    """Run the full WFO + gate-v2 evaluation for the regime-conditional variant."""
    if cfg is None:
        cfg = _make_config()

    data_file = _find_data_file()
    if data_file is None:
        print(f"\n[{SYMBOL}] ERROR: no cache/{SYMBOL}_*_1h.csv found.")
        return {}

    print(f"[{SYMBOL}] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[{SYMBOL}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print(f"[{SYMBOL}] ERROR: not enough data to form WFO windows.")
        return {}

    grid = cfg.grid
    n_combos = len(grid)
    print(f"\n{'=' * 70}")
    print(f"=== {SYMBOL} OVERNIGHT CARRY (REGIME-CONDITIONAL) -- GATE V2 ===")
    print(f"Windows: {len(windows)} | Train {TRAIN_MONTHS}mo / Test {TEST_MONTHS}mo / Step {STEP_MONTHS}mo")
    print(
        f"Grid: {n_combos} combos (filter_len={cfg.filter_len_values} x "
        f"max_rv={cfg.max_rv_values}) | capital ${cfg.capital:,.0f}"
    )
    print("NOTE: VALIDATION ONLY -- a PASS does NOT wire live routing (Tier-3/Amo).")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []
    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_params(cfg, df_train)
        if best_params is None:
            print(f"  [SKIP] window {win['window_num']} IS: no params produced trades")
            continue

        try:
            oos_result = _run_signals_and_backtest(
                cfg, df_test, filter_len=best_params["filter_len"], max_rv=best_params["max_rv"]
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
                "best_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )
        print(
            f"  W{win['window_num']:02d} IS(fl={best_params['filter_len']},rv={best_params['max_rv']}) "
            f"IS_pf={is_result.profit_factor:.3f} OOS_pf={oos_result.profit_factor:.3f} "
            f"OOS_trades={oos_result.total_trades}"
        )

    if not oos_results:
        print(f"\n[{SYMBOL}] No OOS results -- WFO aborted.")
        return {}

    fixed_params_metrics = _run_fixed_params_sweep(cfg, df)
    param_votes = Counter(
        (r["best_params"]["filter_len"], r["best_params"]["max_rv"]) for r in window_records
    )
    champ_fl, champ_rv = param_votes.most_common(1)[0][0] if param_votes else (0, 0.0)
    champion_params = {"filter_len": champ_fl, "max_rv": champ_rv}
    cost_sweep_metrics = _run_cost_sweep(cfg, df, champion_params)
    gate = _compute_gate_v2(cfg, oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(
        f"  pf_ci_lower={gate['pf_ci_lower']:.4f} p_edge={gate['p_edge']:.4f} "
        f"dsr={gate['dsr']:.4f} mc_dd={gate['mc_95th_dd_pct']:.2f}% "
        f"oos_trades={gate['total_oos_trades']}"
    )
    print(f"  champion: filter_len={champ_fl}, max_rv={champ_rv}")
    for r in gate["core_reasons"] + gate["alt_reasons"]:
        print(f"    {r}")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "overnight_carry_regime",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": now_iso,
        "aux_freshness": {"rolling_wfo": now_iso, "fixed_params": now_iso, "cost_sweep": now_iso},
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
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
            "grid_filter_len": cfg.filter_len_values,
            "grid_max_rv": cfg.max_rv_values,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "mc_95th_dd_window_legacy": gate["mc_95th_dd_window_legacy"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed_params_metrics.get("n_combos_with_trades", 0),
            "combo_results": fixed_params_metrics.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
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
            "wfo_consistency_alt": GATE_WFO_CONSISTENCY_VALUES,
            "cost_survives_through_min": "realistic",
        },
        "champion_params": champion_params,
        "windows": window_records,
        "contract_spec": {
            "symbol": SYMBOL,
            "multiplier": cfg.multiplier,
            "tick_size": cfg.tick_size,
            "commission": cfg.commission,
            "slippage_ticks": cfg.slippage_ticks,
            "capital": cfg.capital,
            "note": "MES OVERNIGHT CARRY (REGIME) -- VALIDATION ONLY; Tier-3/Amo auth for live",
        },
        "lineage": {
            "family": "overnight_carry_regime",
            "rank": 1,
            "parent": "MES_overnight_rank1 (near-miss FAIL, pf_ci_lower 0.9955)",
            "hypothesis": "Overnight equity-carry premium concentrates in calm/uptrend "
            "regimes. Add a volatility-stress gate (skip entry when 20-bar annualized "
            "realized vol > max_rv) on top of the optional SMA trend filter, to drop "
            "selloff sessions (2024 bear cluster). VALIDATION ONLY -- no live routing "
            "without Tier-3 authorization.",
        },
    }

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MES_overnight_regime_rank1.json"
<<<<<<< HEAD
=======
    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"[{SYMBOL}] Verdict written -> {verdict_file}")
    return verdict_doc


def main() -> None:
    cfg = _make_config()
    verdict = run_wfo(cfg)
    if not verdict:
        sys.exit(1)
    final = verdict.get("verdict", "FAIL")
    if final == "PASS":
        print(
            f"\n[PASS] {SYMBOL} regime-conditional overnight carry PASSES gate v2 "
            f"(via {verdict.get('passed_via')}). VALIDATION ONLY -- "
            "Tier-3/Amo authorization required before live routing."
        )
    elif final == "INSUFFICIENT_SAMPLE":
        print(f"\n[INSUFFICIENT_SAMPLE] {SYMBOL}: too few OOS trades to certify.")
    else:
        print(f"\n[FAIL] {SYMBOL} regime-conditional overnight carry FAILS gate v2.")


if __name__ == "__main__":
    main()
