"""
JARVIS TRADER — Scheduled Bayesian Optimization (Phase 7.4)
==========================================================
Re-runs Bayesian optimization monthly against the latest 90 days of data.
If new optimal parameters differ from current ones by > 15%, it alerts the
trader for a manual strategy review.

Implements Roadmap P7.4.
"""

import logging
from datetime import datetime, timedelta, timezone

from backtest.bayesian_optimizer import BayesianOptimizer
from backtest.paper_config import PAPER_CONFIGS

logger = logging.getLogger("jarvis_trader.optimization.rebayes")

class ScheduledRebayes:
    def __init__(self, db_manager):
        self.db = db_manager

    async def run_monthly_rebayes(self) -> dict:
        """
        Execute rebayes cycle for all active instruments.
        """
        logger.info("[Rebayes] Starting monthly parameter re-optimization")

        results = {}

        # 90-day lookback for optimization
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

        for symbol, current_cfg in PAPER_CONFIGS.items():
            if not current_cfg.get("enabled", False):
                continue

            logger.info(f"[Rebayes] Optimizing {symbol}...")

            try:
                optimizer = BayesianOptimizer(
                    symbol=symbol,
                    interval=current_cfg.get("interval", "1h"),
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=current_cfg.get("initial_capital", 10000.0)
                )

                # Run 50 calls for high-fidelity optimization
                opt_result = await optimizer.optimize(n_calls=50)

                if "error" in opt_result:
                    logger.warning(f"[Rebayes] {symbol} failed: {opt_result['error']}")
                    continue

                # 2. Compare with current params
                best_params = opt_result["best_params"]
                current_params = current_cfg.get("stc_params") or current_cfg.get("sma_params")

                if not current_params:
                    logger.warning(f"[Rebayes] {symbol} has no current param block to compare.")
                    continue

                comparison = self._compare_params(current_params, best_params)

                results[symbol] = {
                    "optimal_params": best_params,
                    "current_params": current_params,
                    "max_diff_pct": comparison["max_diff_pct"],
                    "alert_required": comparison["max_diff_pct"] > 0.15,
                    "metrics": opt_result["best_metrics"]
                }

                if results[symbol]["alert_required"]:
                    logger.critical(
                        f"🚨 [REBAYES ALERT] {symbol} optimal parameters have shifted by "
                        f"{comparison['max_diff_pct']:.1%}. Current: {current_params} "
                        f"New: {best_params}. Manual review required."
                    )
                else:
                    logger.info(f"✅ [Rebayes] {symbol} parameters stable (diff={comparison['max_diff_pct']:.1%})")

            except Exception as e:
                logger.error(f"[Rebayes] Unexpected error for {symbol}: {e}")

        return results

    def _compare_params(self, current: dict, new: dict) -> dict:
        """Calculate the maximum percentage difference across shared keys."""
        diffs = []

        # Mapping STC/SMA names if needed
        # (Already mostly aligned in config)

        for key, val in new.items():
            if key in current:
                cur_val = float(current[key])
                new_val = float(val)
                if cur_val != 0:
                    pct_diff = abs(new_val - cur_val) / cur_val
                    diffs.append(pct_diff)

        max_diff = max(diffs) if diffs else 0.0
        return {"max_diff_pct": max_diff}
