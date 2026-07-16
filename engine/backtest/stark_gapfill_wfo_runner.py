#!/usr/bin/env python
"""
Stark TPO actionable signals — Gate v2 Walk-Forward Validation.

NEW FILE. Honest WFO of the Stark TPO strategy's production signals, starting
from SHORT_GAP_FILL — the signal quarantined in VALIDATION_ONLY_STRATEGIES
(agents/pipeline.py:132) — and extended to the full six-signal production
taxonomy (see backtest/stark_gapfill_signals.py::STARK_SIGNALS), because the
other five are allowed-by-default in the autonomous pipeline despite never
having been gate-v2 validated either.

Mirrors ib_wfo_runner.py / the gap_go/gap_fade family discipline EXACTLY:
  * 6/3/3-month WFO windows (train 6mo, OOS 3mo, step 3mo, non-overlapping).
  * 15m bars (the strategy's production evaluation timeframe); RTH-only
    entries; next-bar-open entry via Backtester pending_entry (no look-ahead);
    EOD exit; -5% Backtester max-drawdown kill switch; fixed 1 contract.
  * SMALL pre-registered grids: gap-fill signals stop_atr_mult x min_gap_ticks
    (4 combos); other signals stop_atr_mult only (2 combos — their entry band
    is production-fixed, no second degree of freedom invented).
  * Gate v2 metrics via the canonical _gate_v2_helpers path — identical
    thresholds and metric code to every production runner.

Realistic execution costs (MES micro futures, gap-family tier values):
    commission 0.62/contract, slippage 1 tick (realistic tier).

Usage (from engine/):
    .venv/Scripts/python backtest/stark_gapfill_wfo_runner.py                 # all six signals
    .venv/Scripts/python backtest/stark_gapfill_wfo_runner.py SHORT_GAP_FILL  # one signal
"""
from __future__ import annotations

import itertools
import json
import re
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
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
)
from backtest.stark_gapfill_signals import (  # noqa: E402
    STARK_SIGNALS,
    generate_stark_signals,
    precompute_tpo_columns,
)

SYMBOL = "MES"
MULTIPLIER = 5.0

CAPITAL = 50_000.0
COMMISSION = 0.62
SLIPPAGE_TICKS = 1.0  # realistic tier

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

# Pre-registered grids (small, honest — matching family discipline).
STOP_ATR_MULT_VALUES = [1.5, 2.5]
MIN_GAP_TICKS_VALUES = [0, 8]  # gap-fill signals only

FAMILY_BY_SIGNAL = {
    "SHORT_GAP_FILL": "stark_gapfill_short",
    "LONG_GAP_FILL": "stark_gapfill_long",
    "SHORT_VAH_REJECT": "stark_vah_reject_short",
    "LONG_VAL_BOUNCE": "stark_val_bounce_long",
    "LONG_MOMENTUM": "stark_momentum_long",
    "SHORT_MOMENTUM": "stark_momentum_short",
}

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 0.5},
    "realistic": {"commission": 0.62, "slippage_ticks": 1.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 2.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 3.0},
}

MIN_OOS_TRADES_PER_WINDOW = 1


def _grid_for(signal_type: str) -> list[dict]:
    if signal_type in ("SHORT_GAP_FILL", "LONG_GAP_FILL"):
        return [{"stop_atr_mult": sm, "min_gap_ticks": gt}
                for sm, gt in itertools.product(STOP_ATR_MULT_VALUES, MIN_GAP_TICKS_VALUES)]
    return [{"stop_atr_mult": sm, "min_gap_ticks": 0} for sm in STOP_ATR_MULT_VALUES]


def _find_latest_15m_cache() -> Path:
    """Latest-END-date MES 15m continuous cache file (per CACHE_README rule)."""
    cache = engine_root / "backtest" / "cache"
    best, best_end = None, None
    for f in cache.glob("MES_*_15m_cont.csv"):
        m = re.match(r"MES_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_15m_cont\.csv", f.name)
        if not m:
            continue
        end = m.group(2)
        if best_end is None or end > best_end:
            best, best_end = f, end
    if best is None:
        raise FileNotFoundError(f"no MES_*_15m_cont.csv in {cache}")
    return best


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _run_backtest(
    df_tpo: pd.DataFrame,
    signal_type: str,
    params: dict,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester

    sig = generate_stark_signals(
        df_tpo, signal_type=signal_type,
        stop_atr_mult=params["stop_atr_mult"], min_gap_ticks=params["min_gap_ticks"],
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,           # -5% kill switch
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
        eod_close=True,              # intraday — every position exits at session close
        fixed_contracts=1,           # equal-weight basis (matches gap family)
    )
    return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)


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


def _best_is_params(df_train, signal_type, grid):
    best_pf, best_params, best_result = -1.0, None, None
    for params in grid:
        try:
            r = _run_backtest(df_train, signal_type, params)
        except Exception as exc:
            print(f"    [WARN] IS error {params}: {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf = r.profit_factor
            best_params = dict(params)
            best_result = r
    return best_params, best_result


def _run_fixed_params_sweep(df, signal_type, grid):
    pfs, combo_results = [], []
    for params in grid:
        try:
            r = _run_backtest(df, signal_type, params)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combo_results.append({**params, "pf": round(r.profit_factor, 4),
                                      "trades": r.total_trades})
        except Exception as exc:
            print(f"    [WARN] fixed sweep {params}: {exc}")
    if not pfs:
        return {"fixed_params_min_pf": 0.0, "fixed_params_mean_pf": 0.0,
                "fixed_params_max_pf": 0.0, "n_combos_with_trades": 0, "combo_results": combo_results}
    return {"fixed_params_min_pf": round(float(min(pfs)), 4),
            "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
            "fixed_params_max_pf": round(float(max(pfs)), 4),
            "n_combos_with_trades": len(pfs), "combo_results": combo_results}


def _run_cost_sweep(df, signal_type, champion):
    results, last = {}, None
    for tier in COST_TIER_ORDER:
        c = COST_SWEEP_TIERS[tier]
        try:
            r = _run_backtest(df, signal_type, champion,
                              commission=c["commission"], slippage_ticks=c["slippage_ticks"])
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


def run_family(df: pd.DataFrame, signal_type: str, data_file_name: str) -> None:
    family = FAMILY_BY_SIGNAL[signal_type]
    windows = _generate_windows(df)
    grid = _grid_for(signal_type)
    n_combos = len(grid)
    print(f"\n[{family}] {len(windows)} windows | grid {n_combos} combos")

    oos_results, window_records = [], []
    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        best_params, is_result = _best_is_params(df_train, signal_type, grid)
        if best_params is None:
            print(f"  W{win['window_num']}: SKIP (no valid IS params)")
            continue
        try:
            oos = _run_backtest(df_test, signal_type, best_params)
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
        print(f"[{family}] no OOS results — INSUFFICIENT_SAMPLE.")
        return

    fixed = _run_fixed_params_sweep(df, signal_type, grid)
    votes = Counter(tuple(sorted(r["best_params"].items())) for r in window_records)
    champ_items = votes.most_common(1)[0][0] if votes else tuple(sorted(grid[0].items()))
    champion = dict(champ_items)
    cost = _run_cost_sweep(df, signal_type, champion)
    gate = _compute_gate_v2(oos_results, n_combos, fixed, cost)

    print(f"[{family}] VERDICT {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) | "
          f"pf_ci_lower={gate['pf_ci_lower']} p_edge={gate['p_edge']} "
          f"mc95_dd={gate['mc_95th_dd_pct']}% dsr={gate['dsr']} wfo={gate['wfo_consistency']} "
          f"fixed_min_pf={gate['fixed_params_min_pf']} cost={gate['cost_survives_through']} "
          f"oos_trades={gate['total_oos_trades']}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    out = verdicts_dir / f"{SYMBOL}_{family}_rank1.json"
    doc = {
        "symbol": SYMBOL, "family": family, "rank": 1,
        "verdict": gate["verdict"], "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"], "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "wfo_config": {
            "train_months": TRAIN_MONTHS, "test_months": TEST_MONTHS, "step_months": STEP_MONTHS,
            "n_windows": len(windows), "n_oos_windows": gate["n_oos_windows"],
            "total_oos_trades": gate["total_oos_trades"], "grid_combos": n_combos,
            "stop_atr_mult_grid": STOP_ATR_MULT_VALUES,
            "min_gap_ticks_grid": MIN_GAP_TICKS_VALUES if signal_type in
                ("SHORT_GAP_FILL", "LONG_GAP_FILL") else None,
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
        "champion_params": champion,
        "windows": window_records,
        "lineage": {
            "experiment": "Stark TPO production-signal validation sweep "
                          "(SHORT_GAP_FILL quarantine-exit + the five allowed-by-default "
                          "signals, none previously gate-v2 validated)",
            "signal_type": signal_type,
            "signal_source": "strategies/stark_tpo_strategy.py::_get_actionable_signal "
                             "(production classifier; TPO profile via production "
                             "_calculate_tpo_profile, trailing 96x15m window)",
            "wrapper": "backtest/stark_gapfill_signals.py::generate_stark_signals",
            "data_file": data_file_name, "bar_timeframe": "15m",
            "rth_only": "ET 09:30-16:00 weekdays entries; intraday EOD exit",
            "stop": "ATR(14) multiple from entry (grid) — NOTE: production Stark TPO "
                    "defines no stop; overlay required for bounded-loss gate metrics",
            "targets": "TPO POC (mean-reversion/gap-fill mandate); momentum signals "
                       "entry +/- 1x value-area range (no production target exists)",
            "no_lookahead": "TPO profile trailing-inclusive at signal close; Backtester "
                            "enters next-bar open (pending_entry)",
            "kill_switch": "Backtester max_drawdown=0.05 (-5%)",
        },
    }
    out.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[{family}] verdict -> {out.name}")


def main():
    data_file = _find_latest_15m_cache()
    df = _load_data(data_file)
    print(f"\n[STARK-{SYMBOL}] {data_file.name} | {len(df)} bars | "
          f"{df.index.min().date()} -> {df.index.max().date()}")

    print(f"[STARK-{SYMBOL}] precomputing trailing-24h TPO profiles "
          f"(production _calculate_tpo_profile, once over the full frame)...")
    df = precompute_tpo_columns(df)

    targets = sys.argv[1:] or list(STARK_SIGNALS)
    for signal_type in targets:
        if signal_type not in FAMILY_BY_SIGNAL:
            print(f"[STARK-{SYMBOL}] unknown signal {signal_type!r} — skipping")
            continue
        run_family(df, signal_type, data_file.name)


if __name__ == "__main__":
    main()
