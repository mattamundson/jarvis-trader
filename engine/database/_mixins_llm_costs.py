"""
JARVIS TRADER — LLM Costs Mixin
================================
DatabaseManager mixin providing methods for tracking and querying LLM token
usage and estimated costs per pipeline run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger("jarvis_trader.database")

# Token cost rates (per million tokens)
# NOTE: keep in sync with llm/client.py COST_PER_MTOK (single source of truth).
# 2026-09-01: kimi-k3 was missing — T4 persisted 212 rows at $0.00 for the
# production model. Added all rates present in COST_PER_MTOK.
MODEL_RATES: Dict[str, Dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {
        "input": 3.0,  # $3 per million input tokens
        "output": 15.0,  # $15 per million output tokens
    },
    "claude-haiku-4-5": {
        "input": 0.80,  # $0.80 per million input tokens
        "output": 4.00,  # $4.00 per million output tokens
    },
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Kimi K3 (Moonshot AI) — live production model as of 2026-08. Rates match
    # llm/client.py COST_PER_MTOK (cache-miss rate, conservative).
    "kimi-k3": {"input": 3.0, "output": 15.0},
    "hermes3:latest": {"input": 0.0, "output": 0.0},
    "qwen/qwen3.8-27b": {"input": 0.33, "output": 2.40},
    "qwen/qwen3.8-27b-free": {"input": 0.0, "output": 0.0},
}


class LLMCostsMixin:
    """Methods for the ``pipeline_llm_costs`` table."""

    def record_llm_cost(
        self,
        *,
        run_id: str,
        symbol: str,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """
        Record token usage and estimated cost for a single LLM call within a pipeline run.

        Parameters
        ----------
        run_id : str
            Unique identifier for the pipeline run (e.g., UUID)
        symbol : str
            Trading symbol (e.g., "MES", "MNQ")
        stage : str
            Pipeline stage name (e.g., "technical_analyst", "risk_manager")
        model : str
            Model identifier (e.g., "claude-sonnet-4-6")
        input_tokens : int
            Number of input tokens consumed
        output_tokens : int
            Number of output tokens generated
        """
        # Compute estimated cost in USD
        rates = MODEL_RATES.get(model, {})
        input_cost = (input_tokens / 1_000_000) * rates.get("input", 0.0)
        output_cost = (output_tokens / 1_000_000) * rates.get("output", 0.0)
        estimated_cost_usd = input_cost + output_cost

        sql = """
            INSERT INTO pipeline_llm_costs
                (run_id, symbol, stage, model, input_tokens, output_tokens, estimated_cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (run_id, symbol, stage, model, input_tokens, output_tokens, estimated_cost_usd)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
                logger.debug(
                    f"[DB] record_llm_cost run_id={run_id} stage={stage} "
                    f"tokens_in={input_tokens} tokens_out={output_tokens} cost=${estimated_cost_usd:.4f}"
                )
            finally:
                conn.close()

    def get_cost_summary(self) -> Dict[str, Any]:
        """
        Get a summary of LLM costs across different time windows.

        Returns
        -------
        Dict with keys:
            today_usd : float
                Total cost for today (UTC)
            this_week_usd : float
                Total cost for the past 7 days
            all_time_usd : float
                Total cost across all recorded calls
            cost_per_trade_usd : float
                Average cost per unique run_id (approximation of cost per trade)
            top_expensive_stages : List[Dict]
                Top 5 stages by average input+output tokens, with structure:
                [{"stage": str, "avg_tokens": float}, ...]
        """
        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week_ago = (now_utc - timedelta(days=7)).isoformat()

        with self._lock:
            conn = self._connect()
            try:
                # Today's total cost
                today_row = conn.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS cost FROM pipeline_llm_costs "
                    "WHERE created_at >= ?",
                    (today_start,),
                ).fetchone()
                today_usd = float(today_row["cost"]) if today_row else 0.0

                # Week's total cost
                week_row = conn.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS cost FROM pipeline_llm_costs "
                    "WHERE created_at >= ?",
                    (week_ago,),
                ).fetchone()
                this_week_usd = float(week_row["cost"]) if week_row else 0.0

                # All-time total cost
                all_time_row = conn.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS cost FROM pipeline_llm_costs"
                ).fetchone()
                all_time_usd = float(all_time_row["cost"]) if all_time_row else 0.0

                # Cost per run_id (approximation of cost per trade)
                per_run_row = conn.execute(
                    "SELECT COUNT(DISTINCT run_id) AS run_count FROM pipeline_llm_costs"
                ).fetchone()
                run_count = per_run_row["run_count"] if per_run_row else 0
                cost_per_trade_usd = all_time_usd / run_count if run_count > 0 else 0.0

                # Top 5 expensive stages by average token usage
                stage_rows = conn.execute(
                    """
                    SELECT stage,
                           AVG(input_tokens + output_tokens) AS avg_tokens
                    FROM pipeline_llm_costs
                    GROUP BY stage
                    ORDER BY avg_tokens DESC
                    LIMIT 5
                    """
                ).fetchall()
                top_expensive_stages = [
                    {
                        "stage": str(row["stage"]),
                        "avg_tokens": float(row["avg_tokens"]),
                    }
                    for row in (stage_rows or [])
                ]

                return {
                    "today_usd": today_usd,
                    "this_week_usd": this_week_usd,
                    "all_time_usd": all_time_usd,
                    "cost_per_trade_usd": cost_per_trade_usd,
                    "top_expensive_stages": top_expensive_stages,
                }
            finally:
                conn.close()

    def get_llm_costs_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """
        Get all LLM costs for a specific pipeline run.

        Parameters
        ----------
        run_id : str
            The run identifier

        Returns
        -------
        List[Dict]
            List of cost records with keys: id, run_id, symbol, stage, model,
            input_tokens, output_tokens, estimated_cost_usd, created_at
        """
        sql = "SELECT * FROM pipeline_llm_costs WHERE run_id = ? ORDER BY created_at ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, (run_id,)).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
