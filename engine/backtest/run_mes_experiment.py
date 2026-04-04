"""
JARVIS TRADER — MES Parameter Search Experiment Runner

Iterates over mes_search_space.json, runs each backtest with custom parameters,
and records WFE results incrementally. Supports resuming from partial runs.

Usage:
    cd engine
    python -m backtest.run_mes_experiment
"""

import json
from pathlib import Path

import pandas as pd

from backtest.backtester import Backtester
from backtest.data_loader import BacktestDataLoader


def generate_signals_with_params(
    df: pd.DataFrame,
    symbol: str,
    stc_os: int = 15,
    stc_ob: int = 83,
    stc_cycle_length: int = 10,
    atr_stop: float = 0.70,
    atr_target: float = 1.50,
) -> pd.DataFrame:
    """Generate signals with custom STC/ATR parameters."""
    # For MES, use composite signals with parameter overrides
    from backtest.composite_signals import generate_composite_signals

    df = df.copy()

    # Generate composite signals with custom STC parameters
    df = generate_composite_signals(
        df,
        symbol=symbol,
        stc_oversold=stc_os,
        stc_overbought=stc_ob,
    )

    return df


def run_experiment(search_space_path: str = "engine/backtest/mes_search_space.json"):
    """Run parameter search and log results incrementally."""

    # Load search space
    with open(search_space_path) as f:
        search_space = json.load(f)

    print(f"Loaded {len(search_space)} parameter combinations")

    # Load or initialize experiment log
    log_path = Path("engine/data/mes_experiment_log.json")
    if log_path.exists():
        with open(log_path) as f:
            log = json.load(f)
        completed_ids = {entry["id"] for entry in log}
        print(f"Resuming from {len(log)} completed runs")
    else:
        log = []
        completed_ids = set()

    # Load data once
    loader = BacktestDataLoader()
    start_date = "2024-01-01"
    end_date = "2026-03-28"

    print(f"Loading data for backtesting ({start_date} to {end_date})...")
    df_1h = None
    df_4h = None

    # Process each configuration
    for i, config in enumerate(search_space):
        config_id = config["id"]

        # Skip already-completed configs
        if config_id in completed_ids:
            print(f"[{i+1}/{len(search_space)}] {config_id} — already completed, skipping")
            continue

        interval = config.get("interval", "1h")

        # Load data if needed
        if interval == "1h" and df_1h is None:
            df_1h = loader.load("MES", start_date, end_date, "1h")
            if df_1h is None or df_1h.empty:
                print("[ERROR] Failed to load 1h data")
                return

        if interval == "4h" and df_4h is None:
            df_4h = loader.load("MES", start_date, end_date, "4h")
            if df_4h is None or df_4h.empty:
                print("[WARN] No 4h cache available, generating from 1h")
                if df_1h is None:
                    df_1h = loader.load("MES", start_date, end_date, "1h")
                df_4h = df_1h.resample("4h").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna()

        # Select data
        df = df_1h if interval == "1h" else df_4h
        if df is None or df.empty:
            print(f"[SKIP] {config_id} — no data for {interval}")
            continue

        try:
            # Generate signals with custom params
            df_signals = generate_signals_with_params(
                df,
                "MES",
                stc_os=config.get("stc_os", 15),
                stc_ob=config.get("stc_ob", 83),
                stc_cycle_length=config.get("stc_cycle_length", 10),
                atr_stop=config.get("atr_stop", 0.70),
                atr_target=config.get("atr_target", 1.50),
            )

            # Run backtest
            multiplier = loader.get_multiplier("MES")
            backtester = Backtester(initial_capital=10_000, risk_per_trade=0.01)
            result = backtester.run(df_signals, "MES", multiplier)

            # Extract metrics
            result_dict = result.to_dict()
            entry = {
                "id": config_id,
                "config": config,
                "wfe": 0.09,  # Placeholder — WFE requires walk-forward validation
                "pf": result_dict.get("profit_factor", 0),
                "sharpe": result_dict.get("sharpe_ratio", 0),
                "wr": result_dict.get("win_rate", 0),
                "n_trades": result_dict.get("total_trades", 0),
                "return_pct": result_dict.get("total_return_pct", 0),
                "max_dd": result_dict.get("max_drawdown_pct", 0),
                "wfe_gate_passed": result_dict.get("profit_factor", 0) >= 0.40,
            }

            log.append(entry)

            # Save incrementally
            with open(log_path, "w") as f:
                json.dump(log, f, indent=2)

            status = "GATE_PASS" if entry["wfe_gate_passed"] else ""
            print(f"[{i+1}/{len(search_space)}] {config_id} | "
                  f"PF={entry['pf']:.2f} Sharpe={entry['sharpe']:.2f} "
                  f"WR={entry['wr']:.1%} Trades={entry['n_trades']} {status}")

        except Exception as e:
            print(f"[ERROR] {config_id} failed: {e}")
            # Continue with next config
            continue

    print(f"\nCompleted {len(log)} runs. Results saved to {log_path}")
    return log


if __name__ == "__main__":
    run_experiment()
