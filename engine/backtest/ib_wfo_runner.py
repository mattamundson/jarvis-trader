#!/usr/bin/env python
"""
Corey Initial Balance (IB) — Gate v2 Walk-Forward Validation.

NEW FILE. Honest WFO of the opening-range IB breakout strategy, mirroring the
gap_go/gap_fade family discipline EXACTLY (see run_mgc_trend_rv_filter_rank1.py
and engine/data/gate_v2_verdicts/MES_gap_go_rank1.json):

  * 6/3/3-month WFO windows (train 6mo, OOS test 3mo, step 3mo, non-overlapping).
  * RTH-only bars; entry on the NEXT bar open after a fresh IB breakout close
    (Backtester pending_entry — no look-ahead); opposite-IB stop; EOD exit.
  * Backtester -5% max-drawdown kill switch (max_drawdown=0.05).
  * SMALL pre-registered grid: target_mult x open_minutes (4 combos per mode).
  * Two modes evaluated separately: GO (breakout continuation) and FADE.
  * Gate v2 computed via the canonical wfo_lifecycle / _gate_v2_helpers path —
    identical metric code to every production runner.

Realistic execution costs (MES/MGC micro futures, gap-family tier values):
    per-symbol commission (MES 0.62, MGC 0.85 -- see contract_specs.py),
    slippage 1 tick (realistic tier).

Usage (from engine/):
    .venv/Scripts/python backtest/ib_wfo_runner.py            # both symbols, both modes
    .venv/Scripts/python backtest/ib_wfo_runner.py MES go
"""
from __future__ import annotations

import itertools
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
)
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

# --- Symbol specs ---------------------------------------------------------
SPECS = {
    "MES": {
        "multiplier": 5.0,
        "tick": 0.25,
        # SPECIFIED clean 20mo continuous file (NOT the glob-latest 13.7mo file,
        # which is dirtier: 39% zero-vol + a roll spike). Explicit path on purpose.
        "data_file": "MES_2024-09-22_2026-05-29_5m_cont.csv",
    },
    "MGC": {
        "multiplier": 10.0,
        "tick": 0.10,
        "data_file": "MGC_2024-05-01_2026-05-29_5m_cont.csv",
    },
}

CAPITAL = 50_000.0
COMMISSION = 0.62  # documented default only (MES realistic-tier commission).
                   # Every symbol-aware call site resolves commission via
                   # _commission_for(symbol) instead — MGC's canonical
                   # commission (0.85) differs from MES's (0.62); see
                   # backtest/contract_specs.py::CONTRACT_SPECS.
SLIPPAGE_TICKS = 1.0  # realistic tier

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

# Pre-registered grid (small, honest). target_mult_1 >= 1.5 so GO clears the
# Backtester R:R>=1.2 floor (opposite-IB stop makes 1.0x sub-1.2 R:R by design).
TARGET_MULT_VALUES = [1.5, 2.0]
OPEN_MINUTES_VALUES = [30, 60]
MIN_IB_RANGE_PCT = 0.0  # no extra DOF — keep grid small

# Ratios applied to the swept symbol's canonical commission (_commission_for),
# not absolute dollar values — MES (0.62) and MGC (0.85) have different
# canonical commissions, so a flat absolute tier would misprice one of them.
# Ratios derived from the original MES-only tiers: 0.31/0.62/1.24/2.48 == 0.5x/1x/2x/4x of 0.62.
COST_SWEEP_TIERS = {
    "optimistic": {"commission_ratio": 0.5, "slippage_ticks": 0.5},
    "realistic": {"commission_ratio": 1.0, "slippage_ticks": 1.0},
    "pessimistic": {"commission_ratio": 2.0, "slippage_ticks": 2.0},
    "catastrophic": {"commission_ratio": 4.0, "slippage_ticks": 3.0},
}

MIN_OOS_TRADES_PER_WINDOW = 1


def _commission_for(symbol: str) -> float:
    """Per-symbol commission (IB tier-1 baseline, from contract_specs.CONTRACT_SPECS).

    MES and MGC have different CME/COMEX fee schedules (0.62 vs 0.85 per
    contract); previously a flat COMMISSION constant was applied to both.
    """
    return CONTRACT_SPECS[symbol].commission


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


def _run_signals_and_backtest(
    df: pd.DataFrame,
    symbol: str,
    mode: str,
    target_mult: float,
    open_minutes: int,
    commission: float | None = None,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.ib_breakout_signals import generate_ib_breakout_signals

    if commission is None:
        commission = _commission_for(symbol)

    sig = generate_ib_breakout_signals(
        df,
        mode=mode,
        open_minutes=open_minutes,
        min_ib_range_pct=MIN_IB_RANGE_PCT,
        target_mult_1=target_mult,
        target_mult_2=target_mult * 2.0,
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,           # -5% kill switch
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
        eod_close=True,              # intraday — every position exits at session close
        fixed_contracts=1,          # equal-weight basis (matches gap family)
    )
    return bt.run(sig, symbol=symbol, multiplier=SPECS[symbol]["multiplier"])


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
            windows.append({
                "window_num": wnum,
                "train_start": cursor, "train_end": train_end,
                "test_start": test_start, "test_end": test_end,
                "n_train": len(df_train), "n_test": len(df_test),
            })
            wnum += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= data_end:
            break
    return windows


def _best_is_params(df_train, symbol, mode, grid):
    best_pf, best_params, best_result = -1.0, None, None
    for tm, om in grid:
        try:
            r = _run_signals_and_backtest(df_train, symbol, mode, tm, om)
        except Exception as exc:
            print(f"    [WARN] IS error tm={tm} om={om}: {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf = r.profit_factor
            best_params = {"target_mult": tm, "open_minutes": om}
            best_result = r
    return best_params, best_result


def _run_fixed_params_sweep(df, symbol, mode, grid):
    pfs, combo_results = [], []
    for tm, om in grid:
        try:
            r = _run_signals_and_backtest(df, symbol, mode, tm, om)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combo_results.append({"target_mult": tm, "open_minutes": om,
                                      "pf": round(r.profit_factor, 4), "trades": r.total_trades})
        except Exception as exc:
            print(f"    [WARN] fixed sweep tm={tm} om={om}: {exc}")
    if not pfs:
        return {"fixed_params_min_pf": 0.0, "fixed_params_mean_pf": 0.0,
                "fixed_params_max_pf": 0.0, "n_combos_with_trades": 0, "combo_results": combo_results}
    return {"fixed_params_min_pf": round(float(min(pfs)), 4),
            "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
            "fixed_params_max_pf": round(float(max(pfs)), 4),
            "n_combos_with_trades": len(pfs), "combo_results": combo_results}


def _run_cost_sweep(df, symbol, mode, champion):
    results, last = {}, None
    base_commission = _commission_for(symbol)
    for tier in COST_TIER_ORDER:
        c = COST_SWEEP_TIERS[tier]
        try:
            r = _run_signals_and_backtest(df, symbol, mode, champion["target_mult"],
                                          champion["open_minutes"],
                                          commission=base_commission * c["commission_ratio"],
                                          slippage_ticks=c["slippage_ticks"])
            passes = r.profit_factor > 1.0 and r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(r.profit_factor, 4), "trades": r.total_trades, "passes": passes}
            if passes:
                last = tier
        except Exception as exc:
            print(f"    [WARN] cost sweep {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last or "none", "tier_results": results}


def _compute_gate_v2(oos_results, n_grid, fixed_metrics, cost_metrics):
    from backtest.deflated_sharpe import deflated_sharpe_ratio
    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    oos_sharpes = [r.sharpe_ratio for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs) if oos_pfs else 0.0
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    mean_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    n_obs = max(all_trades, 30)
    dsr_r = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_grid, n_obs=n_obs)
    dsr = dsr_r.get("dsr", 0.0) if isinstance(dsr_r, dict) else float(dsr_r)

    wfo_consistency = classify_wfo_consistency(oos_pfs)
    fixed_min_pf = fixed_metrics.get("fixed_params_min_pf", 0.0)
    cost_via = cost_metrics.get("cost_survives_through", "none")
    cost_idx = COST_TIER_ORDER.index(cost_via) if cost_via in COST_TIER_ORDER else -1
    cost_passes = cost_idx >= COST_TIER_ORDER.index("realistic")

    core_pass = (pf_ci_lower >= GATE_PF_CI_LOWER and p_edge >= GATE_P_EDGE
                 and mc_95th_dd <= GATE_MC_DD_CORE and dsr >= GATE_DSR)
    alt_pass = (dsr >= GATE_DSR_ALT and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
                and fixed_min_pf >= GATE_FIXED_PARAMS_MIN_PF and cost_passes
                and mc_95th_dd <= GATE_MC_DD_ALT)

    if core_pass:
        verdict, via = "PASS", "core"
    elif alt_pass:
        verdict, via = "PASS", "alt"
    else:
        verdict, via = "FAIL", None

    return {
        "verdict": verdict, "passed_via": via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "pf_ci_lower": round(pf_ci_lower, 4), "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6), "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6), "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_min_pf,
        "fixed_params_mean_pf": fixed_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_via,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
    }


def run_one(symbol: str, mode: str) -> dict:
    spec = SPECS[symbol]
    data_file = engine_root / "backtest" / "cache" / spec["data_file"]
    df = _load_data(data_file)
    print(f"\n[IB-{symbol}-{mode}] {data_file.name} | {len(df)} bars | "
          f"{df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    grid = list(itertools.product(TARGET_MULT_VALUES, OPEN_MINUTES_VALUES))
    n_combos = len(grid)
    print(f"[IB-{symbol}-{mode}] {len(windows)} windows | grid {n_combos} combos "
          f"(target_mult {TARGET_MULT_VALUES} x open_minutes {OPEN_MINUTES_VALUES})")

    oos_results, window_records = [], []
    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        best_params, is_result = _best_is_params(df_train, symbol, mode, grid)
        if best_params is None:
            print(f"  W{win['window_num']}: SKIP (no valid IS params)")
            continue
        try:
            oos = _run_signals_and_backtest(df_test, symbol, mode,
                                            best_params["target_mult"], best_params["open_minutes"])
        except Exception as exc:
            print(f"  W{win['window_num']}: OOS error {exc}")
            continue
        oos_results.append(oos)
        window_records.append({
            "window": win["window_num"],
            "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
            "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
            "best_params": best_params,
            "is_pf": round(is_result.profit_factor, 3), "is_trades": is_result.total_trades,
            "oos_pf": round(oos.profit_factor, 3), "oos_dd": round(oos.max_drawdown_pct, 4),
            "oos_sharpe": round(oos.sharpe_ratio, 3), "oos_trades": oos.total_trades,
        })
        print(f"  W{win['window_num']} {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}: "
              f"IS PF={is_result.profit_factor:.2f}({is_result.total_trades}) "
              f"OOS PF={oos.profit_factor:.2f} DD={oos.max_drawdown_pct:.1%} "
              f"Sh={oos.sharpe_ratio:.2f} n={oos.total_trades}")

    if not oos_results:
        print(f"[IB-{symbol}-{mode}] no OOS results.")
        return {}

    fixed = _run_fixed_params_sweep(df, symbol, mode, grid)
    from collections import Counter
    votes = Counter((r["best_params"]["target_mult"], r["best_params"]["open_minutes"])
                    for r in window_records)
    champ = votes.most_common(1)[0][0] if votes else (TARGET_MULT_VALUES[0], OPEN_MINUTES_VALUES[-1])
    champion = {"target_mult": champ[0], "open_minutes": champ[1]}
    cost = _run_cost_sweep(df, symbol, mode, champion)
    gate = _compute_gate_v2(oos_results, n_combos, fixed, cost)

    print(f"[IB-{symbol}-{mode}] VERDICT {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) | "
          f"pf_ci_lower={gate['pf_ci_lower']} p_edge={gate['p_edge']} "
          f"mc95_dd={gate['mc_95th_dd_pct']}% dsr={gate['dsr']} wfo={gate['wfo_consistency']} "
          f"fixed_min_pf={gate['fixed_params_min_pf']} cost={gate['cost_survives_through']} "
          f"oos_trades={gate['total_oos_trades']}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    out = verdicts_dir / f"{symbol}_ib_{mode}_rank1.json"
    doc = {
        "symbol": symbol, "family": f"ib_{mode}", "rank": 1,
        "verdict": gate["verdict"], "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"], "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "wfo_config": {
            "train_months": TRAIN_MONTHS, "test_months": TEST_MONTHS, "step_months": STEP_MONTHS,
            "n_windows": len(windows), "n_oos_windows": gate["n_oos_windows"],
            "total_oos_trades": gate["total_oos_trades"], "grid_combos": n_combos,
            "target_mult_grid": TARGET_MULT_VALUES, "open_minutes_grid": OPEN_MINUTES_VALUES,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"], "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"], "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"], "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed.get("n_combos_with_trades", 0),
            "combo_results": fixed.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost.get("tier_results", {}),
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER, "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE, "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr_core": GATE_DSR, "dsr_alt": GATE_DSR_ALT,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
            "wfo_consistency_alt": GATE_WFO_CONSISTENCY_VALUES,
            "cost_survives_through_min": "realistic",
        },
        "champion_params": {**champion, "mode": mode},
        "windows": window_records,
        "lineage": {
            "experiment": "Corey Initial Balance opening-range family (honest gate-v2 WFO)",
            "mechanical_rule": mode,
            "signal_source": "backtest/ib_signals.py::compute_initial_balance (faithful Corey port)",
            "wrapper": "backtest/ib_breakout_signals.py",
            "data_file": spec["data_file"], "bar_timeframe": "5m",
            "rth_only": "ET 09:30-16:00 weekdays; intraday EOD exit",
            "stop": "opposite IB extreme", "targets": "IB-range multiples",
            "no_lookahead": "fresh IB breakout on close; Backtester enters next-bar open (pending_entry)",
            "kill_switch": "Backtester max_drawdown=0.05 (-5%)",
        },
    }
    out.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[IB-{symbol}-{mode}] verdict -> {out.name}")
    return doc


def main():
    args = sys.argv[1:]
    if len(args) == 2:
        run_one(args[0], args[1])
        return
    for symbol in ("MES", "MGC"):
        for mode in ("go", "fade"):
            run_one(symbol, mode)


if __name__ == "__main__":
    main()
