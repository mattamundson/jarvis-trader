"""
JARVIS TRADER -- auto_calibrate.py
===================================
Standalone background service to automatically run the Walk-Forward Validator
against short windows for MCL and MNQ. It extracts the highest-scoring
parameters and dumps them into adaptive_config.json for dynamic STC tuning.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from backtest.data_loader import BacktestDataLoader
from backtest.walk_forward import WalkForwardValidator

logger = logging.getLogger(__name__)

# Config paths
ENGINE_ROOT = Path(__file__).parent.parent
ADAPTIVE_CONFIG_PATH = ENGINE_ROOT / "data" / "adaptive_config.json"

async def run_weekly_calibration() -> None:
    """
    Executes a fast grid 4-month (3mo train, 1mo test) Walk Forward Optimization
    on MCL and MNQ at 15m and 1h intervals.
    Generates dynamic parameter overwrites to combat decay.
    """
    logger.info("Starting Weekly Adaptive Walk-Forward Calibration...")

    symbols = ["MCL", "MNQ"]
    timeframes = ["15m", "1h"]

    loader = BacktestDataLoader()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=120)  # Roughly 4 months

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # We will use shorter windows for adaptive auto-tuning
    validator = WalkForwardValidator(train_months=3, test_months=1, step_months=1)

    adaptive_results: Dict[str, Any] = {}

    for symbol in symbols:
        adaptive_results[symbol] = {}
        for tf in timeframes:
            logger.info(f"[Auto-Calibrate] Processing {symbol} - {tf}")
            try:
                df = loader.load(symbol, start_str, end_str, tf)
                if df is None or df.empty:
                    logger.warning(f"No data for {symbol} - {tf}, skipping.")
                    continue

                multiplier = loader.get_multiplier(symbol)

                result_payload = validator.run(
                    df=df,
                    symbol=symbol,
                    multiplier=multiplier,
                    capital=10000.0,
                    fast=True,             # Fast grid is essential for memory safety
                    adaptive_regime=True,  # Match live settings
                    volume_filter=False,
                    mtf_filter=False
                )

                # Extract best params from the most recent valid window
                windows = result_payload.get("windows", [])
                if windows:
                    latest_window = windows[-1]
                    best_params = latest_window.get("best_params", {})

                    if best_params:
                        adaptive_results[symbol][tf] = {
                            "stc_os": best_params.get("stc_oversold", 15.0),
                            "stc_ob": best_params.get("stc_overbought", 83.0),
                            "wfe": result_payload["summary"].get("wfe", 0),
                            "updated_at": datetime.now().isoformat()
                        }
                        logger.info(f"Recorded best params for {symbol} {tf}: {best_params}")
            except Exception as e:
                logger.error(f"Failed to auto-calibrate {symbol} {tf}: {e}", exc_info=True)

    # Save to JSON State Bank
    try:
        ADAPTIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ADAPTIVE_CONFIG_PATH, "w") as f:
            json.dump(adaptive_results, f, indent=2)
        logger.info(f"Successfully saved adaptive configs to {ADAPTIVE_CONFIG_PATH.name}")
    except Exception as save_err:
        logger.error(f"Failed to save adaptive config: {save_err}")

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_weekly_calibration())
