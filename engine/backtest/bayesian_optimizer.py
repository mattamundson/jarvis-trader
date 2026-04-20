"""
JARVIS TRADER — Bayesian Parameter Optimizer
=============================================
Sprint E1: Replaces grid search with Gaussian Process Bayesian optimization.

Uses scikit-optimize (gp_minimize) when available; falls back to random search.

Objective: maximize sharpe * profit_factor (3x fewer evaluations than grid search).

Usage:
    python -m backtest.bayesian_optimizer --symbol MCL --interval 1h \
        --start 2024-01-01 --end 2026-04-01
"""

from __future__ import annotations

import argparse
import logging
import random
from typing import Optional

from backtest.backtester import BacktestResult
from backtest.data_loader import BacktestDataLoader
from backtest.optimizer import _run_with_params

logger = logging.getLogger(__name__)

# ── Availability check ────────────────────────────────────────────────────────

try:
    from skopt import gp_minimize
    from skopt.space import Integer, Real

    _SKOPT_AVAILABLE = True
except ImportError:
    _SKOPT_AVAILABLE = False
    logger.warning(
        "[BayesOpt] scikit-optimize not installed — using random search fallback. "
        "Install with: pip install scikit-optimize"
    )

# ── Search space bounds ───────────────────────────────────────────────────────

SEARCH_SPACE = {
    "stc_os_min": 10,
    "stc_os_max": 30,
    "stc_ob_min": 75,
    "stc_ob_max": 95,
    "stop_mult_min": 0.4,
    "stop_mult_max": 1.2,
    "t1_mult_min": 1.0,
    "t1_mult_max": 3.0,
}

MIN_TRADES_FOR_SCORE = 3

# Two-tier penalty keeps the optimizer from escaping to zero-trade extremes:
#   _NO_TRADE_PENALTY   < _LOSING_STRATEGY_PENALTY < 0 < profitable score
# The GP therefore prefers "lose a little" over "produce no trades" — which is
# the correct ordering: a losing run gives gradient information; zero trades do not.
_LOSING_STRATEGY_PENALTY = -500.0   # hard gate for PF < 1.0
_NO_TRADE_PENALTY = -501.0          # one step worse than any losing run


def _score_result(result: Optional[BacktestResult]) -> float:
    """
    Scoring tiers (higher = better):
      - No result / < MIN_TRADES: -501  (below any real run — closes zero-trade escape hatch)
      - PF < 1.0:                  -500  (hard gate — losing strategy, but above no-trades)
      - PF >= 1.0:                  max(sharpe, 0) × min(pf, 20)   [always ≥ 0]
    """
    if result is None or result.total_trades < MIN_TRADES_FOR_SCORE:
        return _NO_TRADE_PENALTY
    if result.profit_factor < 1.0:
        return _LOSING_STRATEGY_PENALTY
    pf = min(result.profit_factor, 20.0)
    sr = max(result.sharpe_ratio, 0.0)
    return sr * pf


def _params_from_list(values: list) -> dict:
    """Convert a [stc_os, stc_ob, stop_mult, t1_mult] list to param dict."""
    stc_os, stc_ob, stop_mult, t1_mult = values
    return {
        "stc_oversold": int(stc_os),
        "stc_overbought": int(stc_ob),
        "atr_stop_mult": float(stop_mult),
        "atr_target_mult": float(t1_mult),
        "regime_filter": True,
    }


class BayesianOptimizer:
    """
    Bayesian optimization over STC + ATR strategy parameters.

    Uses Gaussian Process surrogate model (gp_minimize) when scikit-optimize
    is available; falls back to random search otherwise.
    """

    def __init__(
        self,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100_000.0,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self._df_base = None
        self._multiplier: float = 1.0

    def _load_data(self) -> bool:
        """Load and cache backtest data. Returns False if no data."""
        loader = BacktestDataLoader()
        df = loader.load(self.symbol, self.start_date, self.end_date, self.interval)
        if df is None or df.empty:
            logger.error(
                "[BayesOpt] No data for %s %s %s–%s",
                self.symbol,
                self.interval,
                self.start_date,
                self.end_date,
            )
            return False
        self._df_base = df
        self._multiplier = loader.get_multiplier(self.symbol)
        return True

    def _evaluate(self, param_values: list) -> float:
        """
        Single objective evaluation. Minimizes negative score (gp_minimize minimizes).
        """
        params = _params_from_list(param_values)
        result = _run_with_params(
            self._df_base.copy(),
            self._multiplier,
            self.initial_capital,
            **params,
        )
        score = _score_result(result)
        return -score  # minimize negative => maximize score

    def _result_metrics(self, param_values: list) -> dict:
        """Run a single backtest and return the full metrics dict."""
        params = _params_from_list(param_values)
        result = _run_with_params(
            self._df_base.copy(),
            self._multiplier,
            self.initial_capital,
            **params,
        )
        if result is None:
            return {"sharpe": 0.0, "profit_factor": 0.0, "win_rate": 0.0, "trades": 0}
        return {
            "sharpe": round(result.sharpe_ratio, 4),
            "profit_factor": round(min(result.profit_factor, 999.0), 4),
            "win_rate": round(result.win_rate, 2),
            "trades": result.total_trades,
        }

    # ── Bayesian search ───────────────────────────────────────────────────────

    def _run_bayesian(self, n_calls: int, n_initial_points: int) -> tuple[list, float]:
        """
        Run gp_minimize over the search space.
        Returns (best_param_values, best_negative_score).
        """
        space = [
            Integer(SEARCH_SPACE["stc_os_min"], SEARCH_SPACE["stc_os_max"], name="stc_os"),
            Integer(SEARCH_SPACE["stc_ob_min"], SEARCH_SPACE["stc_ob_max"], name="stc_ob"),
            Real(SEARCH_SPACE["stop_mult_min"], SEARCH_SPACE["stop_mult_max"], name="stop_mult"),
            Real(SEARCH_SPACE["t1_mult_min"], SEARCH_SPACE["t1_mult_max"], name="t1_mult"),
        ]

        logger.info(
            "[BayesOpt] Starting GP Bayesian search: %d calls, %d initial random points",
            n_calls,
            n_initial_points,
        )

        res = gp_minimize(
            func=self._evaluate,
            dimensions=space,
            n_calls=n_calls,
            n_initial_points=n_initial_points,
            acq_func="EI",
            random_state=42,
            verbose=False,
        )

        return list(res.x), float(res.fun)

    # ── Random search fallback ────────────────────────────────────────────────

    def _run_random(self, n_calls: int) -> tuple[list, float]:
        """
        Random search over n_calls combinations.
        Returns (best_param_values, best_negative_score).
        """
        logger.info("[BayesOpt] Random search fallback: %d evaluations", n_calls)

        best_values: list = []
        best_neg_score = float("inf")

        rng = random.Random(42)

        for i in range(n_calls):
            stc_os = rng.randint(SEARCH_SPACE["stc_os_min"], SEARCH_SPACE["stc_os_max"])
            stc_ob = rng.randint(SEARCH_SPACE["stc_ob_min"], SEARCH_SPACE["stc_ob_max"])
            stop_mult = round(
                rng.uniform(SEARCH_SPACE["stop_mult_min"], SEARCH_SPACE["stop_mult_max"]), 2
            )
            t1_mult = round(
                rng.uniform(SEARCH_SPACE["t1_mult_min"], SEARCH_SPACE["t1_mult_max"]), 2
            )

            values = [stc_os, stc_ob, stop_mult, t1_mult]
            neg_score = self._evaluate(values)

            if neg_score < best_neg_score:
                best_neg_score = neg_score
                best_values = values

            if (i + 1) % 10 == 0:
                logger.debug(
                    "[BayesOpt] Random search progress: %d/%d (best score=%.4f)",
                    i + 1,
                    n_calls,
                    -best_neg_score,
                )

        return best_values, best_neg_score

    # ── Public interface ──────────────────────────────────────────────────────

    async def optimize(self, n_calls: int = 50) -> dict:
        """
        Run Bayesian (or random fallback) optimization.

        Args:
            n_calls: Total number of objective evaluations (default: 50).

        Returns:
            {
                "best_params": {"stc_os": int, "stc_ob": int, "stop_mult": float, "t1_mult": float},
                "best_score": float,
                "best_metrics": {"sharpe": float, "profit_factor": float, "win_rate": float, "trades": int},
                "n_calls": int,
                "method": "bayesian" | "random_fallback"
            }
        """
        if not self._load_data():
            return {
                "error": f"No data available for {self.symbol} {self.interval} {self.start_date}–{self.end_date}",
                "best_params": None,
                "best_score": 0.0,
                "best_metrics": None,
                "n_calls": 0,
                "method": "none",
            }

        n_initial = min(10, n_calls // 5)

        if _SKOPT_AVAILABLE:
            method = "bayesian"
            best_values, best_neg_score = self._run_bayesian(n_calls, n_initial)
        else:
            method = "random_fallback"
            best_values, best_neg_score = self._run_random(n_calls)

        best_score = -best_neg_score
        best_params_raw = _params_from_list(best_values)
        best_metrics = self._result_metrics(best_values)

        best_params = {
            "stc_os": best_params_raw["stc_oversold"],
            "stc_ob": best_params_raw["stc_overbought"],
            "stop_mult": round(best_params_raw["atr_stop_mult"], 4),
            "t1_mult": round(best_params_raw["atr_target_mult"], 4),
        }

        logger.info(
            "[BayesOpt] Done — method=%s best_score=%.4f params=%s metrics=%s",
            method,
            best_score,
            best_params,
            best_metrics,
        )

        return {
            "best_params": best_params,
            "best_score": round(best_score, 6),
            "best_metrics": best_metrics,
            "n_calls": n_calls,
            "method": method,
        }


# ── CLI entry point ───────────────────────────────────────────────────────────


async def _run_cli(symbol: str, interval: str, start: str, end: str, n_calls: int) -> None:
    import json

    opt = BayesianOptimizer(symbol, interval, start, end)
    result = await opt.optimize(n_calls=n_calls)
    print(json.dumps(result, indent=2))


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description="JARVIS Bayesian Parameter Optimizer")
    parser.add_argument("--symbol", default="MCL")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--n-calls", type=int, default=50)
    args = parser.parse_args()

    asyncio.run(_run_cli(args.symbol, args.interval, args.start, args.end, args.n_calls))


if __name__ == "__main__":
    main()
