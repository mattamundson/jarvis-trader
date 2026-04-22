"""CLI entry point for MES parameter search experiments."""

from __future__ import annotations

import argparse
import os
import sys

# Add engine directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_single_experiment(symbol: str, config_used: dict, log_path: str | None = None) -> dict:
    """Run one walk-forward experiment and return result dict."""
    from strategies.experiment_log import EXPERIMENT_LOG_PATH, ExperimentLog

    log = ExperimentLog(log_path or EXPERIMENT_LOG_PATH)

    try:
        from backtest.walk_forward import run_walk_forward_for_params

        result = run_walk_forward_for_params(
            symbol=symbol,
            timeframe=config_used.get("timeframe", "1h"),
            stc_os=config_used.get("stc_os", 15),
            stc_ob=config_used.get("stc_ob", 83),
            stop_atr_mult=config_used.get("stop_atr_mult", 0.50),
            t1_atr_mult=config_used.get("t1_atr_mult", 1.00),
            regime_required=config_used.get("regime_required", 4),
        )
    except (ImportError, AttributeError) as exc:
        # run_walk_forward_for_params not available — stub result
        result = {
            "error": str(exc),
            "wfe": 0.0,
            "pf_insample": 0.0,
            "pf_walkforward": 0.0,
        }
    except Exception as exc:
        result = {
            "error": str(exc),
            "wfe": 0.0,
            "pf_insample": 0.0,
            "pf_walkforward": 0.0,
        }

    record = {
        "config_used": config_used,
        "wfe": result.get("wfe", 0.0),
        "pf_insample": result.get("pf_insample", 0.0),
        "pf_walkforward": result.get("pf_walkforward", 0.0),
        "sharpe_walkforward": result.get("sharpe_walkforward", 0.0),
        "trade_count": result.get("trade_count", 0),
        "walkforward_window_months": result.get("window_months", 3),
    }
    log.log(record)
    print(
        f"  WFE={record['wfe']:.3f} | PF_wf={record['pf_walkforward']:.2f}"
        f" | config={config_used}"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MES parameter search experiments")
    parser.add_argument("--symbol", default="MES")
    parser.add_argument("--config", required=True, help="Path to search space JSON")
    parser.add_argument("--n", type=int, default=1, help="Number of experiments to run")
    parser.add_argument("--log", help="Path to experiment log JSON (optional)")
    args = parser.parse_args()

    from strategies.experiment_log import EXPERIMENT_LOG_PATH, ExperimentLog
    from strategies.search_strategy import select_next_config

    log_path = args.log or EXPERIMENT_LOG_PATH
    log = ExperimentLog(log_path)

    print(f"Running {args.n} experiment(s) on {args.symbol}...")
    for i in range(args.n):
        config = select_next_config(log, args.config, seed=i)
        print(f"Experiment {i + 1}/{args.n}: {config}")
        run_single_experiment(args.symbol, config, log_path)

    top = log.top_n(3)
    print("\n=== TOP 3 CONFIGS ===")
    for rank, r in enumerate(top, 1):
        print(
            f"  #{rank}: WFE={r['wfe']:.3f}"
            f" | PF_wf={r.get('pf_walkforward', 0):.2f}"
            f" | {r['config_used']}"
        )


if __name__ == "__main__":
    main()
