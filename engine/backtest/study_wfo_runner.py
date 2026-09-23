#!/usr/bin/env python
"""
Generic Gate-v2 Walk-Forward runner for the ThinkScript strategy sweep.

One harness for every Corey/Saty study. A study is any module
``backtest.studies.<name>_signals`` exposing MODES / grid(mode) / generate(df,
mode, **params) (see backtest/studies/__init__.py). The runner is identical in
discipline to ib_wfo_runner.py / the Saty PR #46 runner — 6/3/3 WFO, small grid,
-5% kill switch, realistic costs, full gate-v2 metric path — but study-agnostic.

Usage (from engine/):
    .venv/Scripts/python backtest/study_wfo_runner.py --study saty --symbol MES --mode go
    .venv/Scripts/python backtest/study_wfo_runner.py --study saty            # all symbols x modes
    .venv/Scripts/python backtest/study_wfo_runner.py --study tscore --symbols MES,MGC
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
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
    per_window_adequacy_enforced,
    per_window_sample_adequate,
)
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.cpcv import generate_cpcv_folds  # noqa: E402
from backtest.studies import load_study  # noqa: E402

# OOS access ledger (ml-pitfalls-defense pitfall #4, #234) is a diagnostic
# contamination cap; wiring it here is best-effort and must never affect a
# gate-v2 verdict. A missing/broken ledger, or a hit on the quarterly cap,
# is logged but does not block the caller.
try:
    from analytics.oos_access_ledger import OOSBudgetExceeded, record_if_within_budget
except Exception:  # pragma: no cover - diagnostic-only import
    record_if_within_budget = None
    OOSBudgetExceeded = Exception  # sentinel so the except clause below still type-checks


def _log_oos_access(symbol: str, purpose: str) -> None:
    """Best-effort record of an OOS-touching gate-v2 evaluation. Never raises."""
    if record_if_within_budget is None:
        return
    try:
        record_if_within_budget(f"{purpose}:{symbol}", now=datetime.now(timezone.utc))
    except OOSBudgetExceeded as exc:
        print(f"[OOS-LEDGER][WARN] quarterly OOS-access cap reached: {exc}")
    except Exception:  # pragma: no cover - diagnostic-only, must not affect verdicts
        pass

# Vetted continuous 5m files per symbol (gitignored cache).
DATA_FILES = {
    "MES": "MES_2024-09-22_2026-05-29_5m_cont.csv",
    "MGC": "MGC_2024-05-01_2026-05-29_5m_cont.csv",
    "MCL": "MCL_2025-01-29_2026-06-12_5m_cont.csv",
    "MNQ": "MNQ_2025-04-09_2026-06-12_5m_cont.csv",
}
DEFAULT_SYMBOLS = ["MES", "MGC", "MCL", "MNQ"]

CAPITAL = 50_000.0
TRAIN_MONTHS, TEST_MONTHS, STEP_MONTHS = 6, 3, 3
MIN_OOS_TRADES_PER_WINDOW = 1
# Honest low-power guard: too few OOS windows-with-trades or too few total
# trades -> INSUFFICIENT_SAMPLE rather than a falsely-confident PASS/FAIL.
MIN_OOS_WINDOWS_FOR_VERDICT = 3
MIN_TOTAL_OOS_TRADES_FOR_VERDICT = 20

COST_SWEEP_TIERS = {
    "optimistic": {"commission_mult": 0.5, "slippage_ticks": 0.5},
    "realistic": {"commission_mult": 1.0, "slippage_ticks": 1.0},
    "pessimistic": {"commission_mult": 2.0, "slippage_ticks": 2.0},
    "catastrophic": {"commission_mult": 4.0, "slippage_ticks": 3.0},
}


def _load_data(data_file: Path) -> pd.DataFrame:
<<<<<<< HEAD
    df = pd.read_csv(data_file)
=======
    df = pd.read_csv(data_file)    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
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
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _backtest(study, df, symbol, mode, params, *, commission, slippage_ticks):
    from backtest.backtester import Backtester

    sig = study.generate(df, mode=mode, **params)
    spec = CONTRACT_SPECS[symbol]
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
<<<<<<< HEAD
=======
        spread_ticks=0.5,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        eod_close=True,
        fixed_contracts=1,
    )
    return bt.run(sig, symbol=symbol, multiplier=spec.multiplier)


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start, data_end = df.index.min(), df.index.max()
    windows, cursor, wnum = [], data_start, 1
    while True:
        train_end = cursor + pd.DateOffset(months=TRAIN_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=TEST_MONTHS)
        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end
        df_train = df[(df.index >= cursor) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]
        if len(df_train) >= 30 and len(df_test) >= 30:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": cursor,
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


def _run_cpcv(
    study,
    df,
    symbol,
    mode,
    grid,
    base_comm,
    *,
    n_groups=6,
    n_test_groups=2,
    embargo_sessions=1,
    purge_sessions=14,
):
    """Run CPCV folds and return list of OOS BacktestResults (additive evidence only).

    Reuses _best_is_params (IS selection) and _backtest (OOS evaluation) unchanged.
    CPCV generates C(n_groups, n_test_groups) folds from the full dataset, each with
    purge/embargo applied, giving far more OOS samples than sequential WFO.
    """
    folds = generate_cpcv_folds(
        df.index,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        embargo_sessions=embargo_sessions,
        purge_sessions=purge_sessions,
    )
    oos_results = []
    for fold in folds:
        if len(fold.train_idx) < 30 or len(fold.test_idx) < 30:
            print(
                f"  CPCV fold {fold.fold_id}: SKIP (too few bars "
                f"train={len(fold.train_idx)} test={len(fold.test_idx)})"
            )
            continue
        df_train = df.iloc[fold.train_idx].copy()
        df_test = df.iloc[fold.test_idx].copy()
        best_params, is_result = _best_is_params(study, df_train, symbol, mode, grid, base_comm)
        if best_params is None:
            print(f"  CPCV fold {fold.fold_id}: SKIP (no valid IS params)")
            continue
        try:
            oos = _backtest(
                study, df_test, symbol, mode, best_params, commission=base_comm, slippage_ticks=1.0
            )
        except Exception as exc:
            print(f"  CPCV fold {fold.fold_id}: OOS error {exc}")
            continue
        oos_results.append(oos)
        print(
            f"  CPCV fold {fold.fold_id} groups={fold.test_group_ids}: "
            f"IS PF={is_result.profit_factor:.2f}({is_result.total_trades}) "
            f"OOS PF={oos.profit_factor:.2f} DD={oos.max_drawdown_pct:.1%} "
            f"n={oos.total_trades}"
        )
    return oos_results, folds


def _best_is_params(study, df_train, symbol, mode, grid, base_comm):
    best_pf, best_params, best_result = -1.0, None, None
    for params in grid:
        try:
            r = _backtest(
                study, df_train, symbol, mode, params, commission=base_comm, slippage_ticks=1.0
            )
        except Exception as exc:
            print(f"    [WARN] IS error {params}: {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf, best_params, best_result = r.profit_factor, params, r
    return best_params, best_result


def _fixed_params_sweep(study, df, symbol, mode, grid, base_comm):
    pfs, combo_results = [], []
    for params in grid:
        try:
            r = _backtest(study, df, symbol, mode, params, commission=base_comm, slippage_ticks=1.0)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combo_results.append(
                    {**params, "pf": round(r.profit_factor, 4), "trades": r.total_trades}
                )
        except Exception as exc:
            print(f"    [WARN] fixed sweep {params}: {exc}")
    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": [],
        }
    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combo_results,
    }


def _cost_sweep(study, df, symbol, mode, champion, base_comm):
    results, last = {}, None
    for tier in COST_TIER_ORDER:
        c = COST_SWEEP_TIERS[tier]
        try:
            r = _backtest(
                study,
                df,
                symbol,
                mode,
                champion,
                commission=base_comm * c["commission_mult"],
                slippage_ticks=c["slippage_ticks"],
            )
            passes = r.profit_factor > 1.0 and r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {
                "pf": round(r.profit_factor, 4),
                "trades": r.total_trades,
                "passes": passes,
            }
            if passes:
                last = tier
        except Exception as exc:
            print(f"    [WARN] cost sweep {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last or "none", "tier_results": results}


def _compute_regime_conditional(oos_window_data: list) -> dict:
    """POST-HOC regime-conditional breakdown. NEVER affects gate verdicts.

    Args:
        oos_window_data: list of (BacktestResult, df_test) from the OOS loop.

    Returns:
        A dict with keys: classifier, by_regime_vol, by_regime, by_vol, note.
        On any error returns {"error": <str>} so callers can always proceed.
    """
    try:
        from backtest.regime_conditional import (
            assign_vol_terciles,
            bucket_trades,
            tag_regime_vol,
        )

        all_trades = []
        regime_by_entry: dict = {}
        rv_by_entry: dict = {}
        all_rv_values = []

        for oos_result, df_test in oos_window_data:
            if df_test is None or df_test.empty:
                continue
            try:
                df_tagged = tag_regime_vol(df_test)
            except Exception:
                continue

            # Build per-entry-timestamp lookups from this window's tagged bars.
            for trade in oos_result.trades:
                key = trade.entry_date
                # Find the nearest bar at or after entry_date (index lookup).
                idx = df_tagged.index
                matches = idx[idx >= key]
                if len(matches) == 0:
                    # Entry is beyond the window; use last bar's values.
                    bar_ts = idx[-1]
                else:
                    bar_ts = matches[0]
                regime_by_entry[key] = df_tagged.loc[bar_ts, "rc_regime"]
                rv_val = df_tagged.loc[bar_ts, "rc_rv_ann_pct"]
                rv_by_entry[key] = float(rv_val) if pd.notna(rv_val) else float("nan")
                all_rv_values.append(rv_by_entry[key])

            all_trades.extend(oos_result.trades)

        if not all_trades:
            return {
                "classifier": "adx>=25 trending; rv tercile per-window",
                "note": "DIAGNOSTIC ONLY - does not affect gate verdict",
                "by_regime_vol": {},
                "by_regime": {},
                "by_vol": {},
                "total_trades_classified": 0,
            }

        import pandas as _pd

        rv_series = _pd.Series([v for v in all_rv_values if v == v])  # drop NaN
        p33, p67 = assign_vol_terciles(rv_series)
        breakdown = bucket_trades(all_trades, regime_by_entry, rv_by_entry, (p33, p67))

        return {
            "classifier": "adx>=25 trending; rv tercile per-window",
            "vol_edges": {"p33": round(p33, 4), "p67": round(p67, 4)},
            "by_regime_vol": breakdown["by_regime_vol"],
            "by_regime": breakdown["by_regime"],
            "by_vol": breakdown["by_vol"],
            "total_trades_classified": len(all_trades),
            "note": "DIAGNOSTIC ONLY - does not affect gate verdict",
        }
    except Exception as exc:
        return {"error": str(exc)}


def _compute_gate_v2(oos_results, n_grid, fixed_metrics, cost_metrics):
    # DSR is computed from the actual per-trade return series (trade_level_dsr),
    # NOT the mean of per-window Sharpes. The old mean-of-window-Sharpes path fed
    # the Bailey/Lopez de Prado deflation an unstable Sharpe (1-2 trade windows
    # yield giant Sharpes) with n_obs floored at 30, producing a Phi(z) that
    # rounds to 1.0 and auto-passes. See _gate_v2_trade_metrics for the rationale.
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    CAPITAL = 50_000.0

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs) if oos_pfs else 0.0
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid, initial_capital=CAPITAL)

    wfo_consistency = classify_wfo_consistency(oos_pfs)
    fixed_min_pf = fixed_metrics.get("fixed_params_min_pf", 0.0)
    cost_via = cost_metrics.get("cost_survives_through", "none")
    cost_idx = COST_TIER_ORDER.index(cost_via) if cost_via in COST_TIER_ORDER else -1
    cost_passes = cost_idx >= COST_TIER_ORDER.index("realistic")

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    # Per-window adequacy: median OOS trades/window. Recorded always; ENFORCED
    # only when GATE_V2_ENFORCE_PER_WINDOW is set (shadow-default OFF -> no verdict
    # change). Closes the necessary-not-sufficient gap where 30+ aggregate trades
    # mask a degenerate per-window distribution (median 1-4 trades, PF inflated by
    # single-trade windows -- e.g. MGC_trend_rank4).
    per_window_trades = [r.total_trades for r in oos_results]
    median_oos_trades_per_window = float(np.median(per_window_trades)) if per_window_trades else 0.0
    per_window_block = per_window_adequacy_enforced() and not per_window_sample_adequate(
        per_window_trades
    )

    # Low-power guard.
    insufficient = (
        len(oos_pfs) < MIN_OOS_WINDOWS_FOR_VERDICT
        or all_trades < MIN_TOTAL_OOS_TRADES_FOR_VERDICT
        or per_window_block
    )
    if insufficient:
        verdict, via = "INSUFFICIENT_SAMPLE", None
    elif core_pass:
        verdict, via = "PASS", "core"
    elif alt_pass:
        verdict, via = "PASS", "alt"
    else:
        verdict, via = "FAIL", None

    return {
        "verdict": verdict,
        "passed_via": via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_min_pf,
        "fixed_params_mean_pf": fixed_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_via,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "median_oos_trades_per_window": median_oos_trades_per_window,
        "per_window_adequate": per_window_sample_adequate(per_window_trades),
    }


def run_one(
    study_name: str,
    symbol: str,
    mode: str,
    *,
    cv: str = "sequential",
    cpcv_groups: int = 6,
    cpcv_test_groups: int = 2,
) -> dict:
    study = load_study(study_name)
    if mode not in study.MODES:
        raise ValueError(f"{study_name}: mode {mode!r} not in {study.MODES}")
    data_file = engine_root / "backtest" / "cache" / DATA_FILES[symbol]
    df = _load_data(data_file)
    base_comm = CONTRACT_SPECS[symbol].commission
    print(
        f"\n[{study_name.upper()}-{symbol}-{mode}] {data_file.name} | {len(df)} bars | "
        f"{df.index.min().date()} -> {df.index.max().date()}"
    )

    grid = study.grid(mode)
    n_combos = len(grid)

    # ------------------------------------------------------------------
    # CPCV mode (opt-in, additive evidence — sequential is unchanged)
    # ------------------------------------------------------------------
    if cv == "cpcv":
        print(
            f"[{study_name.upper()}-{symbol}-{mode}] CPCV mode | "
            f"n_groups={cpcv_groups} n_test_groups={cpcv_test_groups} | grid {n_combos} combos"
        )
        oos_results, folds = _run_cpcv(
            study,
            df,
            symbol,
            mode,
            grid,
            base_comm,
            n_groups=cpcv_groups,
            n_test_groups=cpcv_test_groups,
        )
        if not oos_results:
            print(f"[{study_name.upper()}-{symbol}-{mode}] CPCV: no OOS results.")
            gate = {
                "verdict": "INSUFFICIENT_SAMPLE",
                "passed_via": None,
                "core_verdict": "FAIL",
                "alt_verdict": "FAIL",
                "pf_ci_lower": 0.0,
                "p_edge": 0.0,
                "mc_95th_dd": 1.0,
                "mc_95th_dd_pct": 100.0,
                "dsr": 0.0,
                "wfo_consistency": "NONE",
                "fixed_params_min_pf": 0.0,
                "fixed_params_mean_pf": 0.0,
                "fixed_params_max_pf": 0.0,
                "cost_survives_through": "none",
                "n_oos_windows": 0,
                "n_oos_windows_with_trades": 0,
                "total_oos_trades": 0,
            }
            fixed, cost = {}, {"tier_results": {}}
        else:
            fixed = _fixed_params_sweep(study, df, symbol, mode, grid, base_comm)
            # For cost sweep champion, use most-frequent IS params across folds
            from collections import Counter

            champion = dict(grid[0])  # fallback
            cost = _cost_sweep(study, df, symbol, mode, champion, base_comm)
            gate = _compute_gate_v2(oos_results, n_combos, fixed, cost)
            gate["champion"] = champion
            _log_oos_access(symbol, f"gate_v2_cpcv:{study_name}:{mode}")

        print(
            f"[{study_name.upper()}-{symbol}-{mode}] CPCV VERDICT {gate['verdict']} "
            f"(via {gate['passed_via'] or 'NONE'}) | pf_ci_lower={gate['pf_ci_lower']} "
            f"p_edge={gate['p_edge']} mc95_dd={gate['mc_95th_dd_pct']}% dsr={gate['dsr']} "
            f"wfo={gate['wfo_consistency']} oos_trades={gate['total_oos_trades']}"
        )

        verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
        verdicts_dir.mkdir(parents=True, exist_ok=True)
        # CPCV verdicts use a DIFFERENT filename suffix so they never overwrite sequential rank1
        out = verdicts_dir / f"{symbol}_{study_name}_{mode}_cpcv.json"
        doc = {
            "symbol": symbol,
            "family": f"{study_name}_{mode}",
            "rank": None,
            "verdict": gate["verdict"],
            "passed_via": gate["passed_via"],
            "core_verdict": gate["core_verdict"],
            "alt_verdict": gate["alt_verdict"],
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "wfo_config": {
                "cv_method": "cpcv",
                "cpcv": {
                    "n_groups": cpcv_groups,
                    "n_test_groups": cpcv_test_groups,
                    "n_folds": len(folds),
                    "embargo_sessions": 1,
                    "purge_sessions": 14,
                },
                "n_oos_windows": gate["n_oos_windows"],
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
                "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
                "fixed_params_max_pf": gate["fixed_params_max_pf"],
                "n_combos_with_trades": fixed.get("n_combos_with_trades", 0),
                "combo_results": fixed.get("combo_results", []),
                "cost_survives_through": gate["cost_survives_through"],
                "cost_tier_results": cost.get("tier_results", {}),
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
            "champion_params": {**gate.get("champion", {}), "mode": mode},
            "note": (
                "CPCV verdict is ADDITIVE EVIDENCE ONLY. "
                "It does NOT authorize trading. "
                "Sequential _rank1.json verdict is the authorizing document."
            ),
            "lineage": {
                "experiment": "CPCV supplemental validation (study_wfo_runner --cv cpcv)",
                "study": study_name,
                "mechanical_rule": mode,
                "signal_source": f"backtest/studies/{study.__name__.split('.')[-1]}.py",
                "data_file": DATA_FILES[symbol],
                "bar_timeframe": "5m",
                "rth_only": "ET 09:30-16:00 weekdays; intraday EOD exit",
                "no_lookahead": "levels/anchors from prior sessions; Backtester enters next-bar open",
                "kill_switch": "Backtester max_drawdown=0.05 (-5%)",
            },
        }
<<<<<<< HEAD
=======
        # Record the provenance carried on the frame (see loader).
        from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
        doc = _ip(doc, df=df)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        out.write_text(json.dumps(doc, indent=2, default=str))
        print(f"[{study_name.upper()}-{symbol}-{mode}] CPCV verdict -> {out.name}")
        return doc

    # ------------------------------------------------------------------
    # SEQUENTIAL mode (default, unchanged)
    # ------------------------------------------------------------------
    windows = _generate_windows(df)
    print(f"[{study_name.upper()}-{symbol}-{mode}] {len(windows)} windows | grid {n_combos} combos")

    oos_results, window_records = [], []
    # Collect (oos_result, df_test) pairs for the post-hoc regime-conditional pass.
    # df_test is cheap to keep — it's already in memory during this loop.
    _oos_window_data: list[tuple] = []  # list of (BacktestResult, pd.DataFrame)
    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        best_params, is_result = _best_is_params(study, df_train, symbol, mode, grid, base_comm)
        if best_params is None:
            print(f"  W{win['window_num']}: SKIP (no valid IS params)")
            continue
        try:
            oos = _backtest(
                study, df_test, symbol, mode, best_params, commission=base_comm, slippage_ticks=1.0
            )
        except Exception as exc:
            print(f"  W{win['window_num']}: OOS error {exc}")
            continue
        oos_results.append(oos)
        _oos_window_data.append((oos, df_test))
        window_records.append(
            {
                "window": win["window_num"],
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos.profit_factor, 3),
                "oos_dd": round(oos.max_drawdown_pct, 4),
                "oos_sharpe": round(oos.sharpe_ratio, 3),
                "oos_trades": oos.total_trades,
            }
        )
        print(
            f"  W{win['window_num']} {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}: "
            f"IS PF={is_result.profit_factor:.2f}({is_result.total_trades}) "
            f"OOS PF={oos.profit_factor:.2f} DD={oos.max_drawdown_pct:.1%} "
            f"Sh={oos.sharpe_ratio:.2f} n={oos.total_trades}"
        )

    if not oos_results:
        print(f"[{study_name.upper()}-{symbol}-{mode}] no OOS results.")
        gate = {
            "verdict": "INSUFFICIENT_SAMPLE",
            "passed_via": None,
            "core_verdict": "FAIL",
            "alt_verdict": "FAIL",
            "pf_ci_lower": 0.0,
            "p_edge": 0.0,
            "mc_95th_dd": 1.0,
            "mc_95th_dd_pct": 100.0,
            "dsr": 0.0,
            "wfo_consistency": "NONE",
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "cost_survives_through": "none",
            "n_oos_windows": 0,
            "n_oos_windows_with_trades": 0,
            "total_oos_trades": 0,
        }
        fixed, cost = {}, {"tier_results": {}}
    else:
        fixed = _fixed_params_sweep(study, df, symbol, mode, grid, base_comm)
        from collections import Counter

        votes = Counter(tuple(sorted(r["best_params"].items())) for r in window_records)
        champion = dict(votes.most_common(1)[0][0]) if votes else dict(grid[0])
        cost = _cost_sweep(study, df, symbol, mode, champion, base_comm)
        gate = _compute_gate_v2(oos_results, n_combos, fixed, cost)
        gate["champion"] = champion
        _log_oos_access(symbol, f"gate_v2:{study_name}:{mode}")

    # ------------------------------------------------------------------
    # POST-HOC regime-conditional breakdown (ADDITIVE, never gates verdict)
    # Wrapped in try/except: a failure here MUST NOT affect verdict generation.
    # ------------------------------------------------------------------
    regime_conditional = _compute_regime_conditional(_oos_window_data)

    print(
        f"[{study_name.upper()}-{symbol}-{mode}] VERDICT {gate['verdict']} "
        f"(via {gate['passed_via'] or 'NONE'}) | pf_ci_lower={gate['pf_ci_lower']} "
        f"p_edge={gate['p_edge']} mc95_dd={gate['mc_95th_dd_pct']}% dsr={gate['dsr']} "
        f"wfo={gate['wfo_consistency']} fixed_min_pf={gate['fixed_params_min_pf']} "
        f"cost={gate['cost_survives_through']} oos_trades={gate['total_oos_trades']}"
    )

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    out = verdicts_dir / f"{symbol}_{study_name}_{mode}_rank1.json"
    doc = {
        "symbol": symbol,
        "family": f"{study_name}_{mode}",
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
            "n_combos_with_trades": fixed.get("n_combos_with_trades", 0),
            "combo_results": fixed.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost.get("tier_results", {}),
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
        "champion_params": {**gate.get("champion", {}), "mode": mode},
        "windows": window_records,
        "regime_conditional": regime_conditional,
        "lineage": {
            "experiment": "ThinkScript strategy sweep (generic study_wfo_runner)",
            "study": study_name,
            "mechanical_rule": mode,
            "signal_source": f"backtest/studies/{study.__name__.split('.')[-1]}.py",
            "data_file": DATA_FILES[symbol],
            "bar_timeframe": "5m",
            "rth_only": "ET 09:30-16:00 weekdays; intraday EOD exit",
            "no_lookahead": "levels/anchors from prior sessions; Backtester enters next-bar open",
            "kill_switch": "Backtester max_drawdown=0.05 (-5%)",
        },
    }
    out.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[{study_name.upper()}-{symbol}-{mode}] verdict -> {out.name}")
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--symbols", default=None, help="comma list; default all four")
    ap.add_argument("--mode", default=None)
    ap.add_argument(
        "--cv",
        choices=["sequential", "cpcv"],
        default="sequential",
        help="Cross-validation method. 'sequential' (default) is the unchanged WFO path. "
        "'cpcv' runs Combinatorial Purged CV as additive evidence (writes _cpcv.json, "
        "never overwrites _rank1.json).",
    )
    ap.add_argument(
        "--cpcv-groups",
        type=int,
        default=6,
        help="Number of contiguous time groups for CPCV (default 6 -> C(6,2)=15 folds).",
    )
    ap.add_argument(
        "--cpcv-test-groups",
        type=int,
        default=2,
        help="Number of groups held out per CPCV fold (default 2).",
    )
    args = ap.parse_args()

    study = load_study(args.study)
    symbols = (
        [args.symbol]
        if args.symbol
        else args.symbols.split(",") if args.symbols else DEFAULT_SYMBOLS
    )
    modes = [args.mode] if args.mode else study.MODES

    summary = []
    for symbol in symbols:
        for mode in modes:
            doc = run_one(
                args.study,
                symbol,
                mode,
                cv=args.cv,
                cpcv_groups=args.cpcv_groups,
                cpcv_test_groups=args.cpcv_test_groups,
            )
            summary.append((symbol, mode, doc.get("verdict")))
    print("\n=== SWEEP SUMMARY ===")
    for sym, mode, verdict in summary:
        print(f"  {args.study} {sym} {mode}: {verdict}")


if __name__ == "__main__":
    main()
