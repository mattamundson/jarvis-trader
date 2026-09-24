"""
JARVIS TRADER — Portfolio Capital Allocator (Phase 8.1)
======================================================
Implements dynamic Kelly-fractional sizing across the (strategy, instrument) matrix.
Manages correlated risk using a covariance matrix of recent P&L.

Constraints:
  - Per-cell cap: 25% of margin
  - Per-family cap: 50% (e.g. all 'trend' strategies)
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from database.manager import DatabaseManager

logger = logging.getLogger("jarvis_trader.execution.allocator")

class PortfolioAllocator:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        # (strategy, symbol) -> float
        self.active_weights: Dict[Tuple[str, str], float] = {}

    async def calculate_allocations(self) -> Dict[str, Any]:
        """
        Main entry point: computes optimal weights for all enabled strategy-symbol cells.
        """
        logger.info("[Allocator] Calculating portfolio-level capital allocations")

        # 1. Fetch historical trade data (last 60 days)
        lookback = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        trades = self._fetch_recent_trades(lookback)

        if not trades or len(trades) < 10:
            logger.info("[Allocator] Insufficient trade history. Using default 1% risk.")
            return {"status": "default", "default_risk_pct": 0.01}

        # 2. Group by (strategy, symbol)
        cells_data = self._group_trades_by_cell(trades)

        # 3. Compute Edge and Initial Half-Kelly
        raw_allocations = {}
        for cell_key, pnl_list in cells_data.items():
            if len(pnl_list) < 5:
                raw_allocations[cell_key] = 0.01  # Default to 1% if sparse data
                continue

            win_rate = len([p for p in pnl_list if p > 0]) / len(pnl_list)
            avg_win = (
                np.mean([p for p in pnl_list if p > 0]) if any(p > 0 for p in pnl_list) else 0
            )
            avg_loss = (
                np.mean([abs(p) for p in pnl_list if p < 0])
                if any(p < 0 for p in pnl_list)
                else 1
            )

            wlr = avg_win / avg_loss if avg_loss > 0 else 1.0

            # Half-Kelly formula
            kelly = (win_rate * wlr - (1 - win_rate)) / wlr if wlr > 0 else 0
            raw_allocations[cell_key] = max(0, kelly / 2.0)

        # 4. Covariance Adjustment (Phase 8.1)
        # We build a P&L time series per cell to compute correlations
        final_allocations = self._adjust_for_covariance(raw_allocations, trades)

        # 5. Enforce Hard Caps
        # Per-cell cap: 2.5% risk
        # Per-family cap: 5.0% risk (e.g. all 'trend')
        family_totals = {}
        for (strategy, symbol), alloc in final_allocations.items():
            # Basic family detection (e.g. MES_trend -> 'trend')
            family = strategy.split("_")[-1] if "_" in strategy else "other"
            family_totals[family] = family_totals.get(family, 0.0) + alloc

            # Per-cell cap
            final_allocations[(strategy, symbol)] = min(alloc, 0.025)

        # Per-family scaling
        for family, total in family_totals.items():
            if total > 0.05:
                scale = 0.05 / total
                for (strategy, symbol) in final_allocations:
                    if strategy.endswith(family) or (family == "other" and "_" not in strategy):
                        final_allocations[(strategy, symbol)] *= scale

        self.active_weights = final_allocations

        logger.info(f"[Allocator] Computed allocations for {len(final_allocations)} cells")
        return {
            "status": "success",
            "allocations": {f"{k[0]}:{k[1]}": v for k, v in final_allocations.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _adjust_for_covariance(self, raw_allocs: dict, trades: List[Dict]) -> dict:
        """
        Scale down allocations if cells are highly correlated.
        """
        if not raw_allocs:
            return {}

        # Create a pivot table of daily P&L per cell.
        # Tolerant parse (2026-08-17): exit_time rows can be ISO with or without
        # microseconds/offset (e.g. "2026-07-01T00:50:04"), which strict inference
        # rejected and killed the whole allocator at boot. format="mixed" + coerce
        # parses each row independently; malformed rows become NaT (dropped below).
        df_trades = pd.DataFrame(trades)
        df_trades["date"] = pd.to_datetime(
            df_trades["exit_time"], format="mixed", errors="coerce", utc=True
        ).dt.date

        # Extract cell key components
        def get_strategy(params_json):
            try:
                params = json.loads(params_json) if params_json else {}
                return params.get("strategy_name", "unknown")
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                # Malformed strategy_params must not be silently bucketed as
                # "unknown" — that corrupts the correlation matrix and the
                # correlation-adjusted allocations with no trace. Log, then
                # apply the safe fallback.
                logger.warning(
                    "[Allocator] Malformed strategy_params in covariance pivot "
                    "(%r) — bucketing as 'unknown': %s",
                    params_json,
                    exc,
                )
                return "unknown"

        df_trades["cell"] = df_trades.apply(
            lambda x: f"{get_strategy(x['strategy_params'])}:{x['symbol']}", axis=1
        )

        daily_pnl = df_trades.pivot_table(index="date", columns="cell", values="pnl", aggfunc="sum")
        daily_pnl = daily_pnl.fillna(0.0)

        if daily_pnl.shape[1] < 2:
            return raw_allocs

        # Correlation matrix
        corr = daily_pnl.corr()

        adjusted = {}
        for (strategy, symbol), alloc in raw_allocs.items():
            cell_id = f"{strategy}:{symbol}"
            if cell_id not in corr.columns:
                adjusted[(strategy, symbol)] = alloc
                continue

            # Average correlation with other cells
            avg_corr = corr[cell_id].mean()
            # Scaling factor: reduce weight as correlation increases
            # 1.0 (uncorrelated) -> 0.5 (highly correlated)
            scaling = 1.0 / (1.0 + max(0, avg_corr))
            adjusted[(strategy, symbol)] = alloc * scaling

        return adjusted

    def _fetch_recent_trades(self, lookback_iso: str) -> List[Dict]:
        sql = "SELECT * FROM paper_trades WHERE status = 'closed' AND exit_time >= ?"
        return self.db.fetch_all(sql, (lookback_iso,))

    def _group_trades_by_cell(self, trades: List[Dict]) -> Dict[Tuple[str, str], List[float]]:
        cells = {}
        for t in trades:
            # Attempt to extract strategy name
            params = t.get("strategy_params")
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "[Allocator] Malformed strategy_params for trade id=%s "
                        "— bucketing as 'unknown': %s",
                        t.get("id"),
                        exc,
                    )
                    params = {}
            if not isinstance(params, dict):
                # NULL or non-dict strategy_params (e.g. JSON that parsed to a
                # list) would crash params.get below; coerce to the safe default.
                params = {}

            strategy = params.get("strategy_name") or t.get("regime") or "unknown"
            symbol = t.get("symbol", "unknown")

            key = (strategy, symbol)
            if key not in cells:
                cells[key] = []

            if t.get("pnl") is not None:
                cells[key].append(float(t["pnl"]))

        return cells

    def get_risk_pct(self, strategy_name: str, symbol: str) -> float:
        """
        Return the optimal risk percentage for a specific (strategy, symbol) pair.
        """
        # Fallback to default if not calculated or not found
        return self.active_weights.get((strategy_name, symbol), 0.01)
