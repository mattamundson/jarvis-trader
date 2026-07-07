"""
Adaptive strategy parameter optimizer.

Uses an n-autoresearch-style 4-state search loop (explore/exploit/combine/ablation)
to autonomously find better STC/ATR parameter combinations.

States:
  explore  — Try diverse parameter categories, high variation
  exploit  — Focus on best-performing category found so far
  combine  — Mix two near-miss parameter sets
  ablation — Remove one component to test necessity

Usage:
    optimizer = StrategyOptimizer(symbol="MES", interval="1h")
    result = optimizer.run_one_iteration()
    # Returns: {kept: bool, composite_score: float, params: dict}

    # Run full loop:
    optimizer.run_loop(max_iterations=50)

CLI usage:
    python -m engine.optimization.strategy_optimizer --symbol MES --dry-run
    python -m engine.optimization.strategy_optimizer --symbol MES --iterations 20
"""

import argparse
import json
import logging
import random
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Allow running as a script (`python optimization/strategy_optimizer.py`)
# in addition to module form (`python -m engine.optimization.strategy_optimizer`).
# When run as a script, the `engine/` parent is not on sys.path, so we add it
# and prefer package-relative imports like `from analytics.xxx import ...`.
_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

logger = logging.getLogger(__name__)

# State file paths
DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "strategy_state.json"
LOG_FILE = DATA_DIR / "optimization_log.jsonl"

# Keep threshold: new score must be >= best * this to be kept
KEEP_THRESHOLD = 0.95

# Default parameter search space
PARAM_SPACE = {
    "stc_os":        {"min": 10, "max": 25, "step": 1},
    "stc_ob":        {"min": 75, "max": 95, "step": 1},
    "atr_stop_mult": {"min": 0.40, "max": 1.00, "step": 0.05},
    "atr_t1_mult":   {"min": 0.80, "max": 2.50, "step": 0.10},
    "atr_t2_mult":   {"min": 1.50, "max": 4.00, "step": 0.25},
}

# Experiment categories (mapped from n-autoresearch)
CATEGORIES = [
    "stc_thresholds",   # STC OS/OB tuning
    "atr_multipliers",  # Stop and target multiplier tuning
    "regime_filter",    # Layer combination testing
    "combine",          # Mix two near-miss experiments
    "ablation",         # Remove one parameter change to test necessity
]


class StrategyOptimizer:
    """
    Adaptive strategy parameter optimizer using explore/exploit/combine/ablation loop.
    """

    def __init__(
        self,
        symbol: str = "MES",
        interval: str = "1h",
        start_date: str = "2024-06-01",
        end_date: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.symbol = symbol
        self.interval = interval
        self.start_date = start_date
        self.end_date = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.dry_run = dry_run

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load or initialize optimizer state."""
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)

        return {
            "best_score": 0.0,
            "best_params": self._default_params(),
            "search_mode": "explore",
            "iterations": 0,
            "consecutive_rejects": 0,
            "near_misses": [],
            "category_stats": {cat: {"attempts": 0, "keeps": 0} for cat in CATEGORIES},
        }

    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)

    def _default_params(self) -> Dict[str, Any]:
        """Return current production parameters as starting point."""
        return {
            "stc_os": 15,
            "stc_ob": 83,
            "atr_stop_mult": 0.70,
            "atr_t1_mult": 1.50,
            "atr_t2_mult": 2.618,
        }

    def _select_category(self) -> str:
        """Select experiment category based on current search mode."""
        mode = self.state["search_mode"]

        if mode == "explore":
            # Sample least-explored categories
            stats = self.state["category_stats"]
            min_attempts = min(s["attempts"] for s in stats.values())
            candidates = [c for c, s in stats.items() if s["attempts"] == min_attempts]
            return random.choice(candidates)

        elif mode == "exploit":
            # Focus on best-performing category
            stats = self.state["category_stats"]
            best_cat = max(
                (c for c in stats if stats[c]["attempts"] > 0),
                key=lambda c: stats[c]["keeps"] / max(stats[c]["attempts"], 1),
                default="stc_thresholds"
            )
            return best_cat

        elif mode == "combine":
            return "combine"

        elif mode == "ablation":
            return "ablation"

        return "stc_thresholds"

    def _mutate_params(self, base_params: Dict[str, Any], category: str) -> Dict[str, Any]:
        """Generate a parameter mutation based on category."""
        params = deepcopy(base_params)

        if category == "stc_thresholds":
            # Mutate STC OS and/or OB
            if random.random() > 0.5:
                space = PARAM_SPACE["stc_os"]
                params["stc_os"] = random.randrange(space["min"], space["max"] + 1, space["step"])
            if random.random() > 0.5:
                space = PARAM_SPACE["stc_ob"]
                params["stc_ob"] = random.randrange(space["min"], space["max"] + 1, space["step"])
            # Ensure OS < OB
            if params["stc_os"] >= params["stc_ob"]:
                params["stc_ob"] = params["stc_os"] + 10

        elif category == "atr_multipliers":
            if random.random() > 0.5:
                space = PARAM_SPACE["atr_stop_mult"]
                vals = [round(space["min"] + i * space["step"], 2)
                        for i in range(int((space["max"] - space["min"]) / space["step"]) + 1)]
                params["atr_stop_mult"] = random.choice(vals)
            if random.random() > 0.5:
                space = PARAM_SPACE["atr_t1_mult"]
                vals = [round(space["min"] + i * space["step"], 2)
                        for i in range(int((space["max"] - space["min"]) / space["step"]) + 1)]
                params["atr_t1_mult"] = random.choice(vals)

        elif category == "combine" and self.state["near_misses"]:
            # Mix two near-miss experiments
            nm = random.choice(self.state["near_misses"])
            best = self.state["best_params"]
            for key in params:
                if key in nm and key in best:
                    # Interpolate between best and near-miss
                    params[key] = (best[key] + nm[key]) / 2
                    if isinstance(best[key], int):
                        params[key] = round(params[key])

        elif category == "ablation":
            # Reset one parameter to default to test if it's actually needed
            default = self._default_params()
            ablate_key = random.choice(list(params.keys()))
            params[ablate_key] = default[ablate_key]

        return params

    def _run_backtest(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run a backtest with given parameters. Returns metrics or None on error."""
        if self.dry_run:
            # Simulate a result for dry-run testing
            import random as rnd
            return {
                "profit_factor": rnd.uniform(1.5, 6.0),
                "sharpe_ratio": rnd.uniform(1.0, 5.0),
                "walk_forward_efficiency": rnd.uniform(0.3, 0.9),
                "max_drawdown_pct": rnd.uniform(0.01, 0.15),
                "trade_count": rnd.randint(20, 100),
                "win_rate": rnd.uniform(0.25, 0.55),
            }

        try:
            # Import backtester — find the right import path
            # Try common patterns:
            try:
                from backtest.backtester import run_backtest
            except ImportError:
                try:
                    from backtest.run_backtest import run_backtest
                except ImportError:
                    logger.error("Cannot import backtester — check module path")
                    return None

            result = run_backtest(
                symbol=self.symbol,
                start=self.start_date,
                end=self.end_date,
                interval=self.interval,
                stc_os=params.get("stc_os", 15),
                stc_ob=params.get("stc_ob", 83),
                atr_stop_mult=params.get("atr_stop_mult", 0.70),
                atr_t1_mult=params.get("atr_t1_mult", 1.50),
            )

            if result is None:
                return None

            # Normalize result keys (handle different naming conventions)
            normalized = {}
            normalized["profit_factor"] = (
                result.get("profit_factor") or result.get("pf") or 1.0
            )
            normalized["sharpe_ratio"] = (
                result.get("sharpe_ratio") or result.get("sharpe") or 0.0
            )
            normalized["walk_forward_efficiency"] = (
                result.get("walk_forward_efficiency") or result.get("wfe") or 0.5
            )
            normalized["max_drawdown_pct"] = (
                result.get("max_drawdown_pct") or result.get("max_drawdown") or 0.10
            )
            normalized["trade_count"] = result.get("trade_count") or result.get("trades") or 0
            normalized["win_rate"] = result.get("win_rate") or 0.0
            return normalized

        except Exception as e:
            logger.error("Backtest error with params %s: %s", params, e)
            return None

    def _update_search_mode(self):
        """Update search mode based on recent performance."""
        stats = self.state["category_stats"]
        total_attempts = sum(s["attempts"] for s in stats.values())
        total_keeps = sum(s["keeps"] for s in stats.values())

        if total_attempts == 0:
            return

        keep_rate = total_keeps / total_attempts
        consecutive_rejects = self.state["consecutive_rejects"]

        if consecutive_rejects >= 10:
            # Plateau detected — switch to combine
            self.state["search_mode"] = "combine"
            self.state["consecutive_rejects"] = 0
        elif keep_rate < 0.20 and total_attempts >= 10:
            # Low keep rate — exploit best category
            self.state["search_mode"] = "exploit"
        elif total_attempts < 10:
            self.state["search_mode"] = "explore"

    def run_one_iteration(self) -> Dict[str, Any]:
        """
        Run one optimization iteration.

        Returns:
            dict with: kept, composite_score, params, category, iteration
        """
        category = self._select_category()
        current_best = self.state["best_params"]
        new_params = self._mutate_params(current_best, category)

        logger.info(
            "Iteration %d | Mode: %s | Category: %s | Params: %s",
            self.state["iterations"] + 1,
            self.state["search_mode"],
            category,
            new_params,
        )

        # Run backtest
        results = self._run_backtest(new_params)

        if results is None:
            self.state["iterations"] += 1
            self._log_experiment(category, new_params, None, False, "CRASH")
            self._save_state()
            return {"kept": False, "composite_score": 0.0, "params": new_params,
                    "category": category, "iteration": self.state["iterations"], "status": "CRASH"}

        # Compute composite score
        from analytics.validation_metrics import composite_score_from_results
        score = composite_score_from_results(results)

        best_score = self.state["best_score"]
        kept = score >= best_score * KEEP_THRESHOLD

        # Update stats
        self.state["category_stats"][category]["attempts"] += 1
        self.state["iterations"] += 1

        if kept:
            self.state["best_score"] = score
            self.state["best_params"] = new_params
            self.state["consecutive_rejects"] = 0
            self.state["category_stats"][category]["keeps"] += 1

            # Track as near-miss for combine mode (any score within 2% of best)
            if score >= best_score * 0.98:
                nm = self.state.setdefault("near_misses", [])
                nm.append(new_params)
                if len(nm) > 10:  # Keep only 10 near-misses
                    nm.pop(0)
        else:
            self.state["consecutive_rejects"] += 1

        self._update_search_mode()
        self._log_experiment(category, new_params, results, kept, "OK")
        self._save_state()

        status = "KEPT" if kept else "REJECTED"
        logger.info(
            "Result: %s | Score: %.4f (best: %.4f) | PF: %.2f | Sharpe: %.2f",
            status, score, self.state["best_score"],
            results.get("profit_factor", 0), results.get("sharpe_ratio", 0),
        )

        return {
            "kept": kept,
            "composite_score": score,
            "best_score": self.state["best_score"],
            "params": new_params,
            "results": results,
            "category": category,
            "iteration": self.state["iterations"],
            "status": status,
        }

    def run_loop(self, max_iterations: int = 50):
        """Run the full optimization loop."""
        logger.info("Starting optimization loop: symbol=%s, interval=%s, max_iter=%d",
                    self.symbol, self.interval, max_iterations)

        # OOS contamination guard (advisory) — ml-pitfalls-defense.md pitfall #4.
        # Each optimization campaign re-consults the held-out data; record it in the
        # OOS-access ledger (added in #234) and WARN if this quarter's cap is already
        # spent. Diagnostic-first per the rule: this records + warns but never blocks
        # the run, and never raises into the loop. Flipping to the enforcing
        # record_if_within_budget() is the ledger author's reserved follow-up.
        try:
            from analytics.oos_access_ledger import budget_status, record_access

            record_access(
                purpose=f"optimizer:{self.symbol}:{self.interval}:{max_iterations}iter",
                extra={"symbol": self.symbol, "interval": self.interval},
            )
            _oos = budget_status()
            if _oos.exceeded:
                logger.warning(
                    "[OOSLedger] %s OOS-access budget spent: %d/%d in %s. Data-snooping "
                    "risk — prefer locking the spec and forward-testing over another "
                    "optimizer pass. Advisory only.",
                    self.symbol, _oos.used, _oos.cap, _oos.quarter,
                )
        except (ImportError, OSError):
            logger.debug("OOS ledger unavailable; continuing without accounting", exc_info=True)

        for _i in range(max_iterations):
            result = self.run_one_iteration()

            if result["status"] == "CRASH":
                # Count consecutive crashes
                crashes = sum(1 for _ in range(3) if "CRASH" in str(result))
                if crashes >= 3:
                    logger.error("3 consecutive crashes — aborting optimization loop")
                    break

        logger.info(
            "Optimization complete. Best score: %.4f | Best params: %s",
            self.state["best_score"],
            self.state["best_params"],
        )
        return self.state["best_params"]

    def _log_experiment(self, category: str, params: dict, results: Optional[dict],
                         kept: bool, status: str):
        """Append experiment to JSONL log file."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "iteration": self.state["iterations"],
            "symbol": self.symbol,
            "interval": self.interval,
            "category": category,
            "params": params,
            "results": results,
            "kept": kept,
            "status": status,
            "composite_score": None,
        }

        try:
            from analytics.validation_metrics import composite_score_from_results
            if results:
                entry["composite_score"] = composite_score_from_results(results)
        except ImportError:
            pass

        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="JARVIS Adaptive Strategy Optimizer")
    parser.add_argument("--symbol", default="MES", help="Futures symbol (e.g. MES, MNQ, MCL)")
    parser.add_argument("--interval", default="1h", help="Timeframe (e.g. 1h, 4h, 1d)")
    parser.add_argument("--iterations", type=int, default=20, help="Max iterations")
    parser.add_argument("--start", default="2024-06-01", help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without real backtests")
    parser.add_argument("--status", action="store_true", help="Show current optimizer state")
    args = parser.parse_args()

    if args.status:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)
            print(json.dumps(state, indent=2))
        else:
            print("No optimizer state found. Run without --status to initialize.")
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    optimizer = StrategyOptimizer(
        symbol=args.symbol,
        interval=args.interval,
        start_date=args.start,
        end_date=args.end,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("DRY RUN MODE — backtests are simulated")

    best = optimizer.run_loop(max_iterations=args.iterations)
    print(f"\nBest parameters found:\n{json.dumps(best, indent=2)}")


if __name__ == "__main__":
    main()
