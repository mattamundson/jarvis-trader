#!/usr/bin/env python
"""
MCL Gate v2 Re-validation — Hypothesis B: Corey Sentiment Overlay

Walk-forward validation of the Bollinger+RSI mean-reversion strategy on MCL
(micro crude oil 1h) using Corey Discord session bias as an entry gate.

Background:
    Hypothesis A (no filter)    — PF 0.855 / 254 trades — FAIL
    Hypothesis C (rv_band gate) — pf_ci_lower=0.284  p_edge=0.000 — FAIL
    Hypothesis B (this):          Corey #market-updates directional bias used
    to suppress entries on bearish-sentiment days.  Infrastructure exists:
        commentary_processor.py → corey_session_bias table (date, directional_bias,
        conviction, message_count, data_quality).
    Design: load bias once per WFO evaluation (not re-fit), apply per-bar via
    the "sentiment_overlay" gate mode in meanrev_signals._build_regime_gate.

Grid (Hypothesis B):
    regime_filter_mode  : ["none", "sentiment_overlay"]
    sentiment_block_bearish : [True, False]   (only active when mode=sentiment_overlay)
    stop_atr_mult       : [1.0, 1.5, 2.0]
    → 3 (mode×block combos) × 3 (stop) = 9 combos
      - mode="none"  × stop=[1.0, 1.5, 2.0]                   → 3 (baseline)
      - mode="sentiment_overlay" × block=[True,False] × stop   → 6 (hypothesis)

BB + RSI params fixed to MEANREV_PARAMS["MCL"] defaults (same as Hyp C):
    bb_period=20, bb_std=2.0, rsi_period=14, rsi_long=30.0,
    rsi_short=70.0  (stop swept, not fixed)

Gate v2 thresholds (CORE path):
    pf_ci_lower >= 1.10
    p_edge      >= 0.95
    mc_95th_dd  <= 5%
    dsr         >= 0.10

ALT path (same as CORE for mean-rev / lower-capital accounts — no $50K exception):
    mc_95th_dd  <= 7%

WFO config (matches Hyp C):
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 1
    STEP_MONTHS  = 1

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mcl_hypothesis_b.py
    .venv/Scripts/python backtest/run_mcl_hypothesis_b.py --fast
"""
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure engine root is on sys.path when called as a script
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MCL"
MULTIPLIER = 100.0  # MCL = 100 barrels × $0.01/tick = $1/tick
CAPITAL = 10_000.0
TICK_SIZE = 0.01
COMMISSION = 0.85
SLIPPAGE_TICKS = 1.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Fixed BB + RSI params (same as Hyp C baseline)
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_LONG = 30.0
RSI_SHORT = 70.0

# Hypothesis B grid
STOP_ATR_VALUES = [1.0, 1.5, 2.0]

# Gate v2 thresholds

MIN_OOS_TRADES_PER_WINDOW = 5


# ---------------------------------------------------------------------------
# DB detection
# ---------------------------------------------------------------------------


def _find_sentiment_db() -> str:
    """Return path to the engine SQLite DB containing corey_session_bias, or ''."""
    candidates = [
        engine_root / "data" / "jarvis_trader.db",
        engine_root / "data" / "jarvis.db",
        engine_root / "data" / "jarvis_db.sqlite",
        engine_root / "data" / "trading.db",
    ]
    # Also glob for any .db in engine/data/
    for p in (engine_root / "data").glob("*.db"):
        if p not in candidates:
            candidates.append(p)
    for p in (engine_root / "data").glob("*.sqlite"):
        if p not in candidates:
            candidates.append(p)

    for p in candidates:
        if not p.exists():
            continue
        try:
            conn = sqlite3.connect(str(p))
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='corey_session_bias'"
            )
            found = cur.fetchone()
            conn.close()
            if found:
                return str(p)
        except Exception:
            continue
    return ""


def _check_sentiment_table(db_path: str) -> dict:
    """Return row count and date range for corey_session_bias."""
    if not db_path:
        return {"rows": 0, "min_date": None, "max_date": None}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM corey_session_bias")
        row = cur.fetchone()
        conn.close()
        return {"rows": row[0] or 0, "min_date": row[1], "max_date": row[2]}
    except Exception:
        return {"rows": 0, "min_date": None, "max_date": None}


# ---------------------------------------------------------------------------
# Data loading + WFO windows
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
# Per-combo evaluation
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    mode: str,
    sentiment_db_path: str,
    sentiment_block_bearish: bool,
    stop_atr_mult: float,
) -> BacktestResult:  # noqa: F821 - lazy: imported inside fn body
    from backtest.backtester import Backtester
    from backtest.meanrev_signals import generate_bollinger_rsi_signals

    df_sig = generate_bollinger_rsi_signals(
        df,
        bb_period=BB_PERIOD,
        bb_std=BB_STD,
        rsi_period=RSI_PERIOD,
        rsi_long=RSI_LONG,
        rsi_short=RSI_SHORT,
        stop_atr_mult=stop_atr_mult,
        regime_filter_mode=mode,
        sentiment_db_path=sentiment_db_path,
        sentiment_block_bearish=sentiment_block_bearish,
    )

    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _build_grid(fast: bool) -> list[dict]:
    """Return list of param dicts covering the full hypothesis B grid."""
    combos: list[dict] = []

    # Baseline: no sentiment gate, stop swept
    stops = [1.5] if fast else STOP_ATR_VALUES
    for stop in stops:
        combos.append(
            {
                "mode": "none",
                "sentiment_block_bearish": False,  # irrelevant when mode=none
                "stop_atr_mult": stop,
            }
        )

    # Hypothesis: sentiment overlay, block_bearish swept, stop swept
    block_vals = [True] if fast else [True, False]
    for block, stop in itertools.product(block_vals, stops):
        combos.append(
            {
                "mode": "sentiment_overlay",
                "sentiment_block_bearish": block,
                "stop_atr_mult": stop,
            }
        )

    return combos


def _label(combo: dict) -> str:
    if combo["mode"] == "none":
        return f"none/stop={combo['stop_atr_mult']:.1f}"
    b = "block_bearish" if combo["sentiment_block_bearish"] else "allow_bearish"
    return f"sentiment/{b}/stop={combo['stop_atr_mult']:.1f}"


def _best_is_params(
    df_train: pd.DataFrame,
    grid: list[dict],
    sentiment_db_path: str,
) -> tuple[dict | None, BacktestResult | None]:  # noqa: F821
    best_pf = -1.0
    best_params = None
    best_result = None

    for combo in grid:
        try:
            result = _run_signals_and_backtest(
                df_train,
                mode=combo["mode"],
                sentiment_db_path=sentiment_db_path,
                sentiment_block_bearish=combo["sentiment_block_bearish"],
                stop_atr_mult=combo["stop_atr_mult"],
            )
        except Exception as exc:
            print(f"    [WARN] IS error ({_label(combo)}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = combo.copy()
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metrics
# ---------------------------------------------------------------------------

from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    _find_latest_cache,  # noqa: E402
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402


def _compute_gate_v2(oos_results: list, n_grid_combos: int) -> dict:
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

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_ALT
        and dsr >= GATE_DSR
    )
    verdict = "PASS" if core_pass else ("PASS_ALT" if alt_pass else "FAIL")

    return {
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "dsr": round(dsr, 4),
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo(fast: bool = False) -> dict:
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MCL")
    print(f"[MCL-HypB] Selected {data_file.name}")

    print(f"[MCL-HypB] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MCL-HypB] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    # Locate sentiment DB
    sentiment_db = _find_sentiment_db()
    if sentiment_db:
        stats = _check_sentiment_table(sentiment_db)
        print(
            f"[MCL-HypB] Sentiment DB: {Path(sentiment_db).name} | "
            f"{stats['rows']} rows | {stats['min_date']} -> {stats['max_date']}"
        )
        if stats["rows"] == 0:
            print(
                "[MCL-HypB] WARN: corey_session_bias is EMPTY — sentiment gate will "
                "fall through to all-True. Run discord backfill first:\n"
                "  .venv/Scripts/python -m discord.cli "
                "--source <discord-export-dir> --trigger-commentary"
            )
    else:
        print(
            "[MCL-HypB] WARN: No DB with corey_session_bias found — "
            "sentiment_overlay mode will behave identically to 'none'.\n"
            "  Run discord backfill to populate the table before trusting these results."
        )

    windows = _generate_windows(df)
    if not windows:
        print("[MCL-HypB] ERROR: not enough data to form windows.")
        return {}

    grid = _build_grid(fast)
    n_combos = len(grid)

    print(f"\n{'=' * 65}")
    print(f"=== MCL HYPOTHESIS B WFO ({'fast' if fast else 'full'} grid) ===")
    print(f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo")
    print(f"Grid: {n_combos} combos")
    for c in grid:
        print(f"  {_label(c)}")
    print(f"{'=' * 65}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts = win["train_start"]
        te = win["train_end"]
        os_ = win["test_start"]
        oe = win["test_end"]

        print(
            f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  "
            f"({win['n_train']} / {win['n_test']} bars)"
        )

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_params(df_train, grid, sentiment_db)

        if best_params is None:
            print(
                f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades or errored)"
            )
            continue

        print(
            f"  Best IS: {_label(best_params)}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                mode=best_params["mode"],
                sentiment_db_path=sentiment_db,
                sentiment_block_bearish=best_params["sentiment_block_bearish"],
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
        print("\n[MCL-HypB] No OOS results — WFO aborted.")
        return {}

    gate = _compute_gate_v2(oos_results, n_grid_combos=n_combos)

    print(f"\n{'=' * 65}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} ===")
    print(f"  pf_ci_lower = {gate['pf_ci_lower']:.3f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge      = {gate['p_edge']:.3f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd  = {gate['mc_95th_dd']:.3%}  (need <= {GATE_MC_DD_CORE:.0%} core / {GATE_MC_DD_ALT:.0%} alt)"
    )
    print(f"  dsr         = {gate['dsr']:.4f}  (need >= {GATE_DSR})")
    print(
        f"  OOS windows = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades = {gate['total_oos_trades']}")
    print(f"{'=' * 65}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verdict_file = verdicts_dir / f"MCL_hyp_b_{ts_str}.json"

    verdict_doc = {
        "symbol": "MCL",
        "family": "mean_reversion",
        "rank": "hypothesis_b_sentiment_overlay",
        "verdict": gate["verdict"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "passed_via": (
            "core"
            if gate["core_verdict"] == "PASS"
            else ("alt" if gate["alt_verdict"] == "PASS" else None)
        ),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "params": {
            "bb_period": BB_PERIOD,
            "bb_std": BB_STD,
            "rsi_period": RSI_PERIOD,
            "rsi_long": RSI_LONG,
            "rsi_short": RSI_SHORT,
            "stop_atr_mult_grid": STOP_ATR_VALUES,
            "regime_filter_mode": "sentiment_overlay",
        },
        "sentiment": {
            "db_path": sentiment_db,
            "table": "corey_session_bias",
            "field": "directional_bias",
            "empty_warning": not bool(sentiment_db)
            or _check_sentiment_table(sentiment_db)["rows"] == 0,
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "grid_combos": n_combos,
            "fast_grid": fast,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "dsr": gate["dsr"],
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr": GATE_DSR,
        },
        "windows": window_records,
        "aux_freshness": {
            "data_file": data_file.name,
            "n_total_oos_trades": gate["total_oos_trades"],
        },
        "n_core_passed": 1 if gate["core_verdict"] == "PASS" else 0,
        "n_alt_passed": 1 if gate["alt_verdict"] == "PASS" else 0,
    }

<<<<<<< HEAD
=======
    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MCL-HypB] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="MCL Hypothesis B Gate v2 WFO (Sentiment Overlay)")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use reduced grid (3 combos vs 9) for faster iteration",
    )
    args = parser.parse_args()

    verdict = run_wfo(fast=args.fast)

    if not verdict:
        print("[MCL-HypB] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    if final == "PASS":
        print("\n[PASS] Hypothesis B PASSES gate v2 (CORE).")
        print(
            "  Next: remove MCL from DO_NOT_TRADE_SYMBOLS and wire sentiment gate into live pipeline."
        )
    elif final == "PASS_ALT":
        print("\n[PASS-ALT] Hypothesis B PASSES gate v2 (ALT routing only).")
        print("  Next: decide whether to ungate MCL under ALT constraints.")
    else:
        print("\n[FAIL] Hypothesis B FAILS gate v2.")
        gate = verdict.get("gate_v2_metrics", {})
        thresholds = verdict.get("thresholds", {})
        for metric, needed_key in [
            ("pf_ci_lower", "pf_ci_lower"),
            ("p_edge", "p_edge"),
            ("mc_95th_dd", "mc_95th_dd_core"),
            ("dsr", "dsr"),
        ]:
            val = gate.get(metric, 0)
            threshold = thresholds.get(needed_key, "?")
            status = "PASS" if _check_metric(metric, val, thresholds) else "FAIL"
            print(f"  {status} {metric}: {val:.4f} (need {threshold})")
        print("  Next: MCL mean-reversion family exhausted — consider Hypothesis D (trend filter).")

        # Warn explicitly if sentiment table was empty
        sentiment_info = verdict.get("sentiment", {})
        if sentiment_info.get("empty_warning"):
            print("\n  NOTE: corey_session_bias was empty when this ran.")
            print(
                "  Run discord backfill, then re-run:\n"
                "    .venv/Scripts/python -m discord.cli "
                "--source <discord-export-dir> --trigger-commentary\n"
                "    .venv/Scripts/python -m backtest.run_mcl_hypothesis_b"
            )


def _check_metric(metric: str, val: float, thresholds: dict) -> bool:
    if metric == "pf_ci_lower":
        return val >= thresholds.get("pf_ci_lower", 1.10)
    if metric == "p_edge":
        return val >= thresholds.get("p_edge", 0.95)
    if metric == "mc_95th_dd":
        return val <= thresholds.get("mc_95th_dd_core", 0.05)
    if metric == "dsr":
        return val >= thresholds.get("dsr", 0.10)
    return False


if __name__ == "__main__":
    main()
