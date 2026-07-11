#!/usr/bin/env python3
"""
JARVIS TRADER -- stark_forge.py
===============================
Task 1 of the Top-5 ROI Priority List: The Historical Proving Ground.
This script tests the `StarkTPOStrategy` against historical data natively without LLM intervention.
Generates an institutional QuantStats teardown to scientifically prove Edge before we cut the AI.

Usage:
  python engine/backtest/stark_forge.py
"""

import logging
import os
import sys
from datetime import datetime, timedelta

try:
    import numpy as np
    import pandas as pd
    import quantstats as qs
    import yfinance as yf
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install pandas numpy yfinance quantstats")
    sys.exit(1)

# Ensure engine path is in sys.path
engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

try:
    from strategies.stark_tpo_strategy import StarkTPOStrategy
except ImportError as e:
    print(f"ERROR: Could not import StarkTPOStrategy. Ensure execution from workspace root. ({e})")
    sys.exit(1)

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def fetch_historical_data(symbol: str = "ES=F", days: int = 60) -> pd.DataFrame:
    """
    Fetch trailing high-res 15m data using yfinance.
    ES=F is the E-mini S&P 500 continuous contract, perfectly correlating with /MES.
    Max 60 days allowed for 15m intervals in yf.
    """
    logger.info(f"Downloading {days} days of 15m data for {symbol}...")
    # yfinance allows 60d max on 15m data, using 59 to be safe from tz overruns
    days = min(days, 59)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date, interval="15m")

    if df.empty:
        logger.error(f"Failed to fetch data for {symbol}")
        return df

    # Standardize column names to lowercase
    df.columns = [c.lower() for c in df.columns]
    logger.info(f"Successfully downloaded {len(df)} candles.")
    return df


def simulate_forge(df: pd.DataFrame) -> pd.Series:
    """
    Blasts the price array through the Stark-TPO strategy and tracks PnL natively.
    Returns a pandas Series of percentage returns per interval.
    """
    logger.info("Igniting the Forge. Processing TPO Arrays...")

    strategy = StarkTPOStrategy(value_area_pct=0.70)

    # We will step through the dataframe starting at day 1 to allow TPO trailing footprint
    # A rolling 24h window (roughly 96 15-minute bars)
    window_size = 96

    returns = np.zeros(len(df))
    in_position = 0      # 1 for Long, -1 for Short, 0 = Flat
    entry_price = 0.0

    # Transaction Cost Model (TCM)
    tick_size = 0.25
    slippage_ticks = 1.0
    # Canonical rate from contract_specs.py (single source of truth) -- was
    # hardcoded to 0.85, which is MGC/MCL's rate, not MES's (0.62).
    commission = CONTRACT_SPECS["MES"].commission  # per contract per side for MES
    multiplier = 5.0  # MES is $5 per point
    capital = 10000.0 # Starting capital

    # Pre-calculated fixed cost per trade leg (commission + slippage)
    slippage_cost = slippage_ticks * tick_size * multiplier
    tcm_cost_per_leg = commission + slippage_cost
    current_equity = capital

    for i in range(window_size, len(df)):
        # Trailing 24h foot print
        window_df = df.iloc[i-window_size:i]
        last_price = df['close'].iloc[i]

        # Calculate TPO math struct
        struct_data = strategy.evaluate_structure(window_df)

        if not struct_data.get("ready"):
            continue

        signal = struct_data.get("actionable_signal", "HOLD")

        # PnL accounting for open positions
        if in_position != 0:
            # Using closing price of this bar against our entry
            point_diff = last_price - df['close'].iloc[i-1]
            pnl_dollars = (point_diff * multiplier * in_position)

            # Simple static stop-loss simulation (If we lost more than 3 points, cut)
            if (last_price - entry_price) * in_position <= -3.0:
                # Stopped out
                logger.debug(f"STOPPED OUT at {last_price}")
                in_position = 0
                returns[i] = (pnl_dollars - tcm_cost_per_leg) / current_equity
                current_equity += (pnl_dollars - tcm_cost_per_leg)
                continue
            else:
                returns[i] = pnl_dollars / current_equity
                current_equity += pnl_dollars

        # Entry Logic (If flat)
        if in_position == 0:
            if "LONG" in signal:
                logger.debug(f"[{df.index[i]}] Gated LONG at {last_price} due to {signal}")
                in_position = 1
                entry_price = last_price
                current_equity -= tcm_cost_per_leg
            elif "SHORT" in signal:
                logger.debug(f"[{df.index[i]}] Gated SHORT at {last_price} due to {signal}")
                in_position = -1
                entry_price = last_price
                current_equity -= tcm_cost_per_leg

        # Exit Logic (Trailing stop or target hit)
        elif in_position == 1 and ("SHORT" in signal): # Flip or flatten
            in_position = 0
            current_equity -= tcm_cost_per_leg
        elif in_position == -1 and ("LONG" in signal):
            in_position = 0
            current_equity -= tcm_cost_per_leg

    # Convert raw list to returns Series mapping the DateTimeIndex
    returns_series = pd.Series(returns, index=df.index)

    total_r = (current_equity - capital) / capital
    logger.info(f"Forge Complete. Final simulated equity: ${current_equity:.2f} ({total_r*100:.2f}%)")

    return returns_series


def generate_quantstats_tearsheet(returns: pd.Series, output_path: str):
    """Generates the institutional teardown from the Returns array."""
    logger.info(f"Generating QuantStats HTML Tear Sheet at {output_path}...")
    qs.extend_pandas()

    # yfinance SPY to match the exact tz-aware index range for benchmark tracking
    # Quantstats needs daily series usually, so if it's intraday we can resample or just plot basic
    daily_returns = returns.resample('D').sum()
    daily_returns = daily_returns[daily_returns != 0.0] # drop flat days

    qs.reports.html(
        daily_returns,
        benchmark="SPY",
        title="Stark-TPO Math Alpha (ES=F 60-Day)",
        output=output_path
    )
    logger.info("Tearsheet success.")

def main():
    print("=========================================")
    print("JARVIS TRADER :: STARK FORGE (TASK 1)")
    print("=========================================")

    out_dir = os.path.join(engine_dir, "../docs/reports/backtests")
    os.makedirs(out_dir, exist_ok=True)
    report_file = os.path.join(out_dir, "stark_tpo_tearsheet.html")

    df = fetch_historical_data("ES=F", 60)
    if df.empty:
        return

    returns = simulate_forge(df)

    generate_quantstats_tearsheet(returns, report_file)
    print("=========================================")
    print(f"Task 1 Complete. View proof at: file:///{report_file.replace(chr(92), '/')}")
    print("=========================================")


if __name__ == "__main__":
    main()
