"""
Run SPY 1h walk-forward validation.

Validates the STC+ATR strategy on SPY using rolling 6m train / 3m test windows
covering 2024-01-01 to 2026-03-31.

Usage:
    cd engine
    .venv/Scripts/python scripts/run_spy_walkforward.py

Parameters applied (from signals.INSTRUMENT_PARAMS["SPY"]):
    STC_OS   = 15
    STC_OB   = 88
    Stop     = 0.30x ATR
    T1       = 1.00x ATR
    T2       = 1.618x ATR
    T3       = 2.618x ATR
    Regime filter = True (blocks EXHAUSTED / COMPRESSION entries)

Results saved to:
    engine/data/wfe_results/spy_1h_walkforward.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure engine root is on path regardless of cwd
ENGINE_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ENGINE_ROOT))

from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.walk_forward import WalkForwardValidator, _serialise_result  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SYMBOL = "SPY"
INTERVAL = "1h"
START_DATE = "2024-01-01"
END_DATE = "2026-03-31"
TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3
CAPITAL = 10_000.0
FAST_GRID = True  # Use fast param grid; set False for exhaustive search

OUTPUT_DIR = ENGINE_ROOT / "data" / "wfe_results"
OUTPUT_FILE = OUTPUT_DIR / "spy_1h_walkforward.json"


def main() -> None:
    print("=" * 65)
    print("JARVIS TRADER — SPY 1h Walk-Forward Validation")
    print(f"Period : {START_DATE} to {END_DATE}")
    print(f"Windows: {TRAIN_MONTHS}m train / {TEST_MONTHS}m test, step {STEP_MONTHS}m")
    print(f"Capital: ${CAPITAL:,.0f}")
    print("=" * 65)

    # ── Load data ──────────────────────────────────────────────────────────
    loader = BacktestDataLoader()
    print(f"\nLoading {SYMBOL} ({INTERVAL}) from {START_DATE} to {END_DATE}...")
    df = loader.load(SYMBOL, START_DATE, END_DATE, INTERVAL)

    if df is None or df.empty:
        print(
            f"\nERROR: No data loaded for {SYMBOL}.\n"
            "Possible causes:\n"
            "  1. POLYGON_API_KEY not set in engine/.env\n"
            "  2. No cached CSV for this date range in engine/backtest/cache/\n"
            "  3. SPY equity data not available on your Polygon plan\n"
            "\nTo pre-cache: set POLYGON_API_KEY in engine/.env, then re-run."
        )
        sys.exit(1)

    multiplier = loader.get_multiplier(SYMBOL)
    print(f"Loaded {len(df)} bars. Contract multiplier: {multiplier}")

    # ── Run walk-forward validation ────────────────────────────────────────
    validator = WalkForwardValidator(
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
    )

    result = validator.run(
        df=df,
        symbol=SYMBOL,
        multiplier=multiplier,
        capital=CAPITAL,
        fast=FAST_GRID,
        adaptive_regime=False,
        volume_filter=False,
        mtf_filter=False,
    )

    summary = result["summary"]
    windows = result["windows"]

    # ── WFE interpretation ─────────────────────────────────────────────────
    wfe = summary["wfe"]
    if wfe > 0.50:
        wfe_label = "GOOD — strategy generalises well"
        verdict = "APPROVED for further validation"
    elif wfe > 0.30:
        wfe_label = "ACCEPTABLE — some degradation in OOS"
        verdict = "CONDITIONAL — review individual windows"
    else:
        wfe_label = "OVERFIT — strategy does not generalise"
        verdict = "REJECTED — do not trade live"

    print(f"\n{'=' * 65}")
    print("FINAL VERDICT")
    print(f"  WFE   : {wfe:.4f}  ({wfe_label})")
    print(f"  Status: {verdict}")
    print(f"{'=' * 65}")

    # ── Build output payload ───────────────────────────────────────────────
    payload = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "train_months": TRAIN_MONTHS,
        "test_months": TEST_MONTHS,
        "step_months": STEP_MONTHS,
        "capital": CAPITAL,
        "fast_grid": FAST_GRID,
        "generated": datetime.now().isoformat(),
        "instrument_params": {
            "stc_os": 15,
            "stc_ob": 88,
            "atr_stop_mult": 0.30,
            "atr_t1_mult": 1.00,
            "atr_t2_mult": 1.618,
            "atr_t3_mult": 2.618,
            "regime_filter": True,
        },
        "summary": summary,
        "verdict": verdict,
        "windows": [],
    }

    for w in windows:
        payload["windows"].append(
            {
                "window": w["window"],
                "train_period": w["train_period"],
                "test_period": w["test_period"],
                "train_bars": w["train_bars"],
                "test_bars": w["test_bars"],
                "best_params": w["best_params"],
                "is_result": _serialise_result(w["is_result"]),
                "oos_result": _serialise_result(w["oos_result"]),
            }
        )

    # ── Save results ───────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2))

    print(f"\nResults saved to: {OUTPUT_FILE}")
    print(
        f"\nSummary:\n"
        f"  Avg IS Return  : {summary['avg_is_return'] * 100:.2f}%\n"
        f"  Avg OOS Return : {summary['avg_oos_return'] * 100:.2f}%\n"
        f"  WFE            : {wfe:.4f}\n"
        f"  Avg OOS Sharpe : {summary['avg_oos_sharpe']:.2f}\n"
        f"  Avg OOS PF     : {summary['avg_oos_profit_factor']:.2f}\n"
        f"  OOS Profitable : {summary['windows_profitable']}/{summary['total_windows']} windows\n"
    )


if __name__ == "__main__":
    main()
