"""
Vol Accuracy Validator — Phase 0 Diagnostic
============================================
Addresses the concern from 2026-04-25: Is the 15.1% realized vol reading
accurate, or is it a data artifact from HB-6 (screenshot parsing)?

This script:
1. Pulls the last 10 days of SPY/QQQ prices from yfinance (live, no screenshots)
2. Computes realized vol using the SAME method as VolatilityTargeter
3. Compares against the engine's reported vol for the current signal
4. Flags if the delta exceeds 3% (artifact threshold)

Run:
    python3 -m engine.scripts.vol_accuracy_check
    python3 -m engine.scripts.vol_accuracy_check --lookback 5  # match signal config
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SIGNAL_FILE = (
    Path(__file__).parent.parent / "strategy_c" / "output" / "strategy_c_plus_live_signal.json"
)


def fetch_live_prices(symbols: list[str], lookback_days: int = 15) -> pd.DataFrame:
    """Fetch recent daily closes from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed — run: pip install yfinance")

    data = yf.download(
        symbols,
        period=f"{lookback_days + 5}d",  # fetch extra to have enough after dropna
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if "Close" in data.columns:
        closes = data["Close"]
    else:
        closes = data

    # Ensure we have a proper DataFrame even for single symbol
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(name=symbols[0])

    return closes.dropna(how="all")


def compute_vol(prices: pd.Series, lookback: int = 10) -> float:
    """Compute annualized realized vol matching VolatilityTargeter.compute_realized_vol."""
    tail = prices.tail(lookback + 1)
    log_rets = np.log(tail / tail.shift(1)).dropna()
    log_rets = log_rets.tail(lookback)
    if len(log_rets) < 3:
        return 15.0  # fallback
    return float(log_rets.std() * np.sqrt(252) * 100)


def run_check(lookback: int = 5) -> dict:
    """
    Compare live-computed vol vs engine-reported vol.

    Returns dict with verdict and all figures.
    """
    # Load signal
    if not SIGNAL_FILE.exists():
        return {"error": f"Signal file not found: {SIGNAL_FILE}"}

    with open(SIGNAL_FILE) as f:
        signal = json.load(f)

    reported_vol = signal["layers"]["vol_targeting"].get("realized_vol_pct", None)
    reported_scale = signal["layers"]["vol_targeting"].get("scale", None)
    signal_date = signal.get("effective_date", "unknown")

    print(f"\n{'='*55}")
    print(f"  JARVIS Vol Accuracy Check")
    print(f"  Signal date: {signal_date}  |  Lookback: {lookback}d")
    print(f"{'='*55}")
    print(f"  Engine reported vol:   {reported_vol:.2f}%")
    print(f"  Engine reported scale: {reported_scale:.4f}")
    print()

    # Fetch live prices
    print("  Fetching SPY + QQQ from yfinance...")
    try:
        df = fetch_live_prices(["SPY", "QQQ"], lookback_days=lookback + 10)
    except Exception as e:
        return {"error": f"Price fetch failed: {e}", "reported_vol": reported_vol}

    if df.empty:
        return {"error": "No price data returned", "reported_vol": reported_vol}

    # Compute vol for each symbol
    spy_vol = compute_vol(df["SPY"] if "SPY" in df.columns else df.iloc[:, 0], lookback)
    qqq_vol = compute_vol(df["QQQ"] if "QQQ" in df.columns else df.iloc[:, 1], lookback)

    # Blended composite (same as VolatilityTargeter — 50/50 blend)
    composite_vol = 0.5 * qqq_vol + 0.5 * spy_vol
    vol_floor = 6.0
    composite_vol = max(composite_vol, vol_floor)

    # Compute what scale would be at 7% target
    vol_target = signal["layers"]["vol_targeting"].get("vol_target_pct", 7.0)
    raw_scale = vol_target / composite_vol
    computed_scale = min(raw_scale, 1.0)

    # Delta analysis
    vol_delta = abs(composite_vol - reported_vol)
    scale_delta = abs(computed_scale - reported_scale)
    artifact_threshold = 3.0  # % vol — flag if diverges more than this

    is_clean = vol_delta <= artifact_threshold
    verdict = "CLEAN" if is_clean else "SUSPECT"
    icon = "OK" if is_clean else "WARNING"

    print(f"  Live SPY vol ({lookback}d):    {spy_vol:.2f}%")
    print(f"  Live QQQ vol ({lookback}d):    {qqq_vol:.2f}%")
    print(f"  Composite (50/50):     {composite_vol:.2f}%")
    print()
    print(f"  Engine reported:       {reported_vol:.2f}%")
    print(f"  Live computed:         {composite_vol:.2f}%")
    print(f"  Delta:                 {vol_delta:+.2f}%")
    print(f"  Verdict:               {icon} {verdict}")
    print()
    print(f"  Scale check:")
    print(f"    Engine reported:     {reported_scale:.4f} ({reported_scale:.1%})")
    print(f"    Live computed:       {computed_scale:.4f} ({computed_scale:.1%})")
    print(f"    Scale delta:         {scale_delta:+.4f}")

    if not is_clean:
        print()
        print("  *** SUSPECT: Delta > 3% — check HB-6 data feed ***")
        print("  Action: Run engine price fetch audit before Monday execution")

    # Print last N bars of price data for manual review
    print(f"\n  Last {lookback} closes:")
    tail = df.tail(lookback + 1)
    for dt, row in tail.iterrows():
        spy_p = row.get("SPY", float("nan"))
        qqq_p = row.get("QQQ", float("nan"))
        print(f"    {str(dt)[:10]}  SPY={spy_p:.2f}  QQQ={qqq_p:.2f}")

    print(f"\n{'='*55}\n")

    return {
        "verdict": verdict,
        "is_clean": is_clean,
        "vol_delta_pct": round(vol_delta, 3),
        "engine_vol": reported_vol,
        "live_spy_vol": round(spy_vol, 3),
        "live_qqq_vol": round(qqq_vol, 3),
        "live_composite_vol": round(composite_vol, 3),
        "engine_scale": reported_scale,
        "live_scale": round(computed_scale, 4),
        "scale_delta": round(scale_delta, 4),
        "lookback_days": lookback,
        "signal_date": signal_date,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="JARVIS Vol Accuracy Check")
    parser.add_argument("--lookback", "-l", type=int, default=5,
                        help="Lookback days (match vol_lookback_days in StrategyCConfig)")
    args = parser.parse_args()
    result = run_check(args.lookback)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)
