"""
Gate-v2 WFO runner for MES calendar strategies.

Strategies:
  - MES_turn_of_month  : Enter last trading day of month (RTH close),
                         exit 3rd trading day of next month (RTH close).
  - MES_pre_fomc       : Enter RTH close day-before FOMC, exit RTH close FOMC day.

Both are LONG-ONLY, time-governed exits, validated against full gate-v2:
    pf_ci_lower >= 1.10, p_edge >= 0.95, mc_95th_dd <= 5%, dsr >= 0.10

VALIDATION ONLY. A PASS does NOT wire live routing (Tier-3/owner-gated).

Usage (from engine/ directory):
    API_KEY=test-key .venv/Scripts/python backtest/run_mes_calendar_rank1.py
    API_KEY=test-key .venv/Scripts/python backtest/run_mes_calendar_rank1.py --strategy turn_of_month
    API_KEY=test-key .venv/Scripts/python backtest/run_mes_calendar_rank1.py --strategy pre_fomc
"""

from __future__ import annotations

import argparse
import json
import sys
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

# ---------------------------------------------------------------------------
# WFO config — same as trend_diversifier template
# ---------------------------------------------------------------------------
TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1
MIN_OOS_TRADES_PER_WINDOW = 1

# MES contract spec
MES_MULTIPLIER = 5.0
MES_TICK_SIZE = 0.25
MES_COMMISSION = 0.62  # per leg IB tier-1
MES_SLIPPAGE_TICKS = 1.0
MES_CAPITAL = 50_000.0

# Cost sweep tiers — same relative ladder as trend runners
_COST_TIERS = {
    "optimistic": {"commission": round(MES_COMMISSION * 0.5, 4), "slippage_ticks": 1.0},
    "realistic": {"commission": MES_COMMISSION, "slippage_ticks": 1.0},
    "pessimistic": {"commission": round(MES_COMMISSION * 2.0, 4), "slippage_ticks": 2.0},
    "catastrophic": {"commission": round(MES_COMMISSION * 4.0, 4), "slippage_ticks": 3.0},
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _find_mes_data() -> Path | None:
    """Locate the deepest MES 1h cache (most rows / latest end date)."""
    data_dir = engine_root / "backtest" / "cache"
    pattern = "MES_*_1h.csv"
    if not list(data_dir.glob(pattern)):
        # Worktree fallback: 4 levels up to repo root -> engine/backtest/cache
        repo_root = engine_root.parent.parent.parent.parent
        main_cache = repo_root / "engine" / "backtest" / "cache"
        if main_cache.exists() and list(main_cache.glob(pattern)):
            data_dir = main_cache
            print(f"[MES] Using main checkout cache: {data_dir}")
    files = list(data_dir.glob(pattern))
    if not files:
        return None
    # Pick by latest end date encoded in filename
    return _find_latest_cache(data_dir, "MES")


def _load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    return df


# ---------------------------------------------------------------------------
# WFO window generation
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


def _run_calendar_backtest(
    signal_fn,
    df: pd.DataFrame,
    commission: float = MES_COMMISSION,
    slippage_ticks: float = MES_SLIPPAGE_TICKS,
) -> object:
    """Generate signals and run backtester for one slice of data."""
    from backtest.backtester import Backtester

    df_sig = signal_fn(df)
    bt = Backtester(
        initial_capital=MES_CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.10,  # wider: calendar hold can span 5 days
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
        eod_close=False,   # calendar trades span multiple days — do NOT close at EOD
        use_targets=False,  # time-governed exit; wide targets never hit
        fixed_contracts=1,  # 1 contract per event for equal weighting
    )
    return bt.run(df_sig, symbol="MES", multiplier=MES_MULTIPLIER)


# ---------------------------------------------------------------------------
# Fixed-params sweep (calendar has no tunable params — run once on full set)
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(signal_fn, df: pd.DataFrame) -> dict:
    """Calendar strategies have no grid — one param-free pass on full data."""
    try:
        result = _run_calendar_backtest(signal_fn, df)
        if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
            pf = result.profit_factor
            return {
                "fixed_params_min_pf": round(pf, 4),
                "fixed_params_mean_pf": round(pf, 4),
                "fixed_params_max_pf": round(pf, 4),
                "n_combos_with_trades": 1,
                "combo_results": [{"params": "calendar", "pf": round(pf, 4), "trades": result.total_trades}],
            }
    except Exception as exc:
        print(f"  [WARN] fixed-params error: {exc}")
    return {
        "fixed_params_min_pf": 0.0,
        "fixed_params_mean_pf": 0.0,
        "fixed_params_max_pf": 0.0,
        "n_combos_with_trades": 0,
        "combo_results": [],
    }


def _run_cost_sweep(signal_fn, df: pd.DataFrame) -> dict:
    """Cost sweep with contiguous-survival rule."""
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = _COST_TIERS[tier]
        try:
            result = _run_calendar_backtest(
                signal_fn, df,
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
    oos_results: list,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest._gate_v2_trade_metrics import (
        trade_level_dsr,
        trade_level_mc_95th_dd,
        trade_level_win_rate_ci_lower,
    )

    # n_grid_combos=1 for calendar (no grid search → no selection bias to deflate DSR)
    N_GRID_COMBOS = 1

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=MES_CAPITAL)
    dsr = trade_level_dsr(oos_results, n_grid_combos=N_GRID_COMBOS, initial_capital=MES_CAPITAL)
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
        "n_core_passed": sum(1 for r in core_reasons if not r.startswith("FAIL")),
        "n_alt_passed": sum(1 for r in alt_reasons if not r.startswith("FAIL")),
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
# Full WFO run for one strategy
# ---------------------------------------------------------------------------


def run_strategy(
    name: str,
    signal_fn,
    df: pd.DataFrame,
) -> dict:
    """Run WFO + gate-v2 for a calendar strategy. Returns verdict dict."""
    windows = _generate_windows(df)
    if not windows:
        print(f"[{name}] ERROR: Not enough data to form WFO windows.")
        return {}

    print(f"\n{'=' * 70}")
    print(f"=== {name} -- GATE V2 VALIDATION ===")
    print(f"Windows: {len(windows)} | Train {TRAIN_MONTHS}mo / Test {TEST_MONTHS}mo / Step {STEP_MONTHS}mo")
    print(f"Capital: ${MES_CAPITAL:,.0f} | MES multiplier ${MES_MULTIPLIER}/pt")
    print("NOTE: VALIDATION ONLY -- PASS does NOT wire live routing (Tier-3/owner).")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        os_, oe = win["test_start"], win["test_end"]
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        # Calendar strategies have no IS optimization; run directly on OOS slice
        try:
            oos_result = _run_calendar_backtest(signal_fn, df_test)
        except Exception as exc:
            print(f"  [SKIP] window {win['window_num']} OOS error: {exc}")
            continue

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": win["window_num"],
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_trades": oos_result.total_trades,
            }
        )
        print(
            f"  Window {win['window_num']:02d} OOS {os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}: "
            f"trades={oos_result.total_trades} pf={oos_result.profit_factor:.3f} "
            f"dd={oos_result.max_drawdown_pct:.4f}"
        )

    if not oos_results:
        print(f"\n[{name}] No OOS results -- WFO aborted.")
        return {}

    total_oos_trades = sum(r.total_trades for r in oos_results)
    print(f"\n[{name}] Total OOS trades across all windows: {total_oos_trades}")

    fixed_params_metrics = _run_fixed_params_sweep(signal_fn, df)
    cost_sweep_metrics = _run_cost_sweep(signal_fn, df)
    gate = _compute_gate_v2(oos_results, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(
        f"  pf_ci_lower={gate['pf_ci_lower']:.4f} p_edge={gate['p_edge']:.4f} "
        f"dsr={gate['dsr']:.4f} mc_dd={gate['mc_95th_dd_pct']:.2f}% "
        f"oos_trades={gate['total_oos_trades']}"
    )
    for r in gate["core_reasons"]:
        print(f"    CORE: {r}")
    for r in gate["alt_reasons"]:
        print(f"    ALT:  {r}")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": "MES",
        "family": "calendar",
        "strategy_name": name,
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
            "grid_combos": 1,
            "note": "Calendar strategy -- no IS parameter grid (no selection bias)",
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
        },
        "contract_spec": {
            "symbol": "MES",
            "multiplier": MES_MULTIPLIER,
            "tick_size": MES_TICK_SIZE,
            "commission": MES_COMMISSION,
            "slippage_ticks": MES_SLIPPAGE_TICKS,
            "capital": MES_CAPITAL,
            "note": "VALIDATION ONLY -- no live routing without Tier-3/Amo authorization",
        },
        "windows": window_records,
        "lineage": {
            "family": "calendar",
            "hypothesis": f"{name}: pure time-based edge (no SMA/momentum). "
            "VALIDATION ONLY -- Tier-3/owner authorization required for live routing.",
        },
    }

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / f"{name}.json"
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"[{name}] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="MES calendar strategy gate-v2 runner")
    ap.add_argument(
        "--strategy",
        choices=["turn_of_month", "pre_fomc", "both"],
        default="both",
        help="Which strategy to run (default: both)",
    )
    args = ap.parse_args()

    data_file = _find_mes_data()
    if data_file is None:
        print("[ERROR] No MES 1h cache found. Run an IB Gateway historical pull first.")
        sys.exit(3)

    print(f"[MES] Loading {data_file.name} ...")
    df_raw = _load_data(data_file)
    print(f"[MES] {len(df_raw)} bars | {df_raw.index.min().date()} -> {df_raw.index.max().date()}")

    from backtest.calendar_signals import (  # noqa: E402
        generate_pre_fomc_signals,
        generate_turn_of_month_signals,
    )

    strategies = []
    if args.strategy in ("turn_of_month", "both"):
        strategies.append(("MES_turn_of_month", generate_turn_of_month_signals))
    if args.strategy in ("pre_fomc", "both"):
        strategies.append(("MES_pre_fomc", generate_pre_fomc_signals))

    results = {}
    for name, fn in strategies:
        doc = run_strategy(name, fn, df_raw)
        results[name] = doc

    print("\n" + "=" * 70)
    print("=== SUMMARY ===")
    for name, doc in results.items():
        if not doc:
            print(f"  {name}: NO RESULT (insufficient data or error)")
            continue
        g = doc.get("gate_v2_metrics", {})
        print(
            f"  {name}: {doc['verdict']} (via {doc.get('passed_via') or 'NONE'}) | "
            f"pf_ci_lower={g.get('pf_ci_lower','?')} p_edge={g.get('p_edge','?')} "
            f"mc_dd={g.get('mc_95th_dd_pct','?')}% dsr={g.get('dsr','?')} "
            f"n_oos_trades={g.get('total_oos_trades','?')}"
        )

    # Exit non-zero if any strategy FAILed (not INSUFFICIENT_SAMPLE — that's honest)
    any_fail = any(
        doc.get("verdict") == "FAIL" for doc in results.values() if doc
    )
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
