"""
Autonomous strategy improvement loop.

Continuously generates, evaluates, and accumulates winning strategy variants.
Inspired by: github.com/rv64m/autotrade

Usage:
    python -m strategy_lab.strategy_loop --symbol MES --max_iterations 50
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Paths are relative to the engine root (CWD when run via -m)
RESULTS_FILE = Path("backtest/results/strategy_lab_results.jsonl")
BEST_STRATEGIES_FILE = Path("backtest/results/strategy_lab_best.json")

FOCUS_AREAS = [
    "improve win rate above 40%",
    "reduce max drawdown below 5%",
    "maximize Sharpe ratio above 2.0",
    "improve Calmar ratio",
    "find edge on faster 15m or 30m timeframe",
    "find robust parameters with wide OB/OS separation",
    "optimize for maximum profit factor",
]


def run_strategy_loop(
    symbol: str = "MES",
    max_iterations: int = 50,
    start: str = "2024-06-01",
    end: str = "2026-03-27",
) -> dict:
    """
    Run the autonomous strategy improvement loop.

    Returns summary dict with eligible_count, best_pf, best_strategy.
    """
    # Ensure engine root on path when called as a library (e.g. from FastAPI)
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if engine_root not in sys.path:
        sys.path.insert(0, engine_root)

    try:
        from llm.client import JarvisLLMClient
    except ImportError:
        logger.error("JarvisLLMClient unavailable — engine.llm.client import failed")
        return {"error": "jarvis_llm_client not importable", "eligible_count": 0}

    from strategy_lab.strategy_evaluator import evaluate_strategy_variant
    from strategy_lab.strategy_generator import generate_strategy_variant

    # Routes through JarvisLLMClient so Anthropic credit-exhaustion silently
    # falls over to Gemini (when GOOGLE_API_KEY is set) and the call is tracked
    # in the cost DB.
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    db_path = os.getenv("JARVIS_LLM_COST_DB", "data/llm_costs.db")
    client = JarvisLLMClient(api_key=api_key, db_path=db_path)
    results: list = []
    best_strategies: list = []
    best_pf = 0.0

    # Ensure output directory exists
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"[STRATEGY LAB] Autonomous loop — {max_iterations} iterations on {symbol}")
    print(f"[STRATEGY LAB] Period: {start} -> {end}")
    print("[STRATEGY LAB] Gates: Risk (DD<15%) | Profit (Sharpe>=1.2, Calmar>=0.8, PF>=1.8)")
    print(f"{'='*60}\n")

    for i in range(max_iterations):
        focus = FOCUS_AREAS[i % len(FOCUS_AREAS)]
        iteration_num = i + 1

        print(f"[{iteration_num:3d}/{max_iterations}] Focus: {focus}")

        # Generate variant
        try:
            variant = generate_strategy_variant(client, results, focus_area=focus)
            params = variant["parameters"]
            name = variant["strategy_name"]
            print(f"         Strategy: {name}")
            print(
                f"         STC {params['stc_oversold']}/{params['stc_overbought']} | "
                f"Stop {params['atr_stop_mult']}x | T1 {params['atr_target_mult']}x | "
                f"TF {params['timeframe']}"
            )
        except Exception as e:
            print(f"         [GENERATE ERROR] {e} -- skipping iteration")
            continue

        # Evaluate
        result = evaluate_strategy_variant(
            variant["parameters"], symbol=symbol, start=start, end=end
        )
        result["strategy_name"] = name
        result["description"] = variant.get("description", "")
        result["iteration"] = iteration_num
        result["focus_area"] = focus
        result["timestamp"] = datetime.now().isoformat()

        verdict = result["verdict"]
        metrics = result.get("metrics", {})
        pf = metrics.get("profit_factor", metrics.get("pf", 0)) or 0
        sharpe = metrics.get("sharpe_ratio", metrics.get("sharpe", 0)) or 0
        n_trades = metrics.get("total_trades", metrics.get("n_trades", 0)) or 0

        verdict_symbol = "ELIGIBLE" if verdict == "ELIGIBLE" else f"x {verdict}"
        print(f"         [{verdict_symbol}] PF={pf:.2f} | Sharpe={sharpe:.2f} | N={n_trades}")

        for violation in result.get("violations", []):
            print(f"           ! {violation}")

        if verdict == "ELIGIBLE" and pf > best_pf:
            best_pf = pf
            best_strategies.append(result)
            print(f"         ** NEW BEST -- PF={pf:.2f}")

            sorted_best = sorted(
                best_strategies,
                key=lambda x: (
                    x.get("metrics", {}).get("profit_factor") or x.get("metrics", {}).get("pf") or 0
                ),
                reverse=True,
            )[:10]
            BEST_STRATEGIES_FILE.write_text(json.dumps(sorted_best, indent=2))

        results.append(result)
        with open(RESULTS_FILE, "a") as f:
            f.write(json.dumps(result) + "\n")

        print()

    eligible_count = sum(1 for r in results if r["verdict"] == "ELIGIBLE")

    print(f"\n{'='*60}")
    print("[STRATEGY LAB COMPLETE]")
    print(f"  Total iterations: {len(results)}/{max_iterations}")
    print(f"  ELIGIBLE: {eligible_count}")
    print(f"  Best PF: {best_pf:.2f}")

    if best_strategies:
        best = max(
            best_strategies,
            key=lambda x: (
                x.get("metrics", {}).get("profit_factor") or x.get("metrics", {}).get("pf") or 0
            ),
        )
        print(f"  Best strategy: {best.get('strategy_name', 'unknown')}")
        p = best.get("parameters", {})
        print(
            f"  Params: STC {p.get('stc_oversold')}/{p.get('stc_overbought')} | "
            f"Stop {p.get('atr_stop_mult')}x | TF {p.get('timeframe')}"
        )

    print(f"  Results: {RESULTS_FILE}")
    print(f"{'='*60}\n")

    return {
        "eligible_count": eligible_count,
        "total_evaluated": len(results),
        "best_pf": best_pf,
        "best_strategy": best_strategies[0] if best_strategies else None,
        "results_file": str(RESULTS_FILE),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="JARVIS Trader Strategy Lab -- Autonomous optimization loop"
    )
    parser.add_argument("--symbol", default="MES", choices=["MES", "MNQ", "MCL"])
    parser.add_argument("--max_iterations", type=int, default=50)
    parser.add_argument("--start", default="2024-06-01")
    parser.add_argument("--end", default="2026-03-27")
    args = parser.parse_args()

    run_strategy_loop(
        symbol=args.symbol,
        max_iterations=args.max_iterations,
        start=args.start,
        end=args.end,
    )
