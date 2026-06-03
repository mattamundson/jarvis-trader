"""
JARVIS TRADER — LLM Cost Tracker
=================================
SQLite-backed cost tracking for all LLM API calls.

Schema:
  llm_calls(
    id INTEGER PRIMARY KEY,
    timestamp TEXT,           -- ISO 8601 UTC timestamp
    model TEXT,               -- e.g. "claude-opus-4-7"
    input_tokens INTEGER,     -- Input token count
    output_tokens INTEGER,    -- Output token count
    cost_usd REAL,            -- Cost in USD
    latency_ms INTEGER,       -- Latency in milliseconds
    agent_name TEXT,          -- Which agent made the call
    success BOOLEAN,          -- True if call succeeded
    provider TEXT             -- Serving provider: 'direct'|'vertex'|'google'|
                              --   'vertex-gemini'|'ollama'|'external' (Task 9)
  )
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class CostTracker:
    """SQLite-backed LLM cost and usage tracker."""

    def __init__(self, db_path: str = "data/llm_costs.db"):
        """
        Initialize the cost tracker.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()
        logger.info(f"✅ CostTracker initialized at {db_path}")

    def _init_db(self):
        """Create the llm_calls table if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                agent_name TEXT DEFAULT 'unknown',
                success BOOLEAN DEFAULT 1,
                provider TEXT DEFAULT 'direct'
            )
            """
        )

        # Task 9 migration: add the provider column to pre-existing databases.
        # ALTER TABLE ADD COLUMN is additive and backfills existing rows with the
        # default ('direct'), so this is safe to run against a live DB on the next
        # CostTracker instantiation (engine restart) — no data loss, no behavior
        # change for callers that omit the new argument.
        cursor.execute("PRAGMA table_info(llm_calls)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "provider" not in existing_cols:
            cursor.execute("ALTER TABLE llm_calls ADD COLUMN provider TEXT DEFAULT 'direct'")

        # Index by timestamp for range queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON llm_calls(timestamp)")
        # Index by model for per-model summaries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_model ON llm_calls(model)")
        # Index by agent for per-agent summaries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent ON llm_calls(agent_name)")
        # Index by provider for the direct-vs-Vertex A/B breakdown
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_provider ON llm_calls(provider)")

        conn.commit()
        conn.close()

    async def log_call(
        self,
        timestamp: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        agent_name: str,
        success: bool,
        provider: str = "direct",
    ) -> None:
        """
        Log a single LLM API call.

        Args:
            timestamp: ISO 8601 UTC timestamp
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            cost_usd: Cost in USD
            latency_ms: Latency in milliseconds
            agent_name: Calling agent name
            success: True if successful
            provider: Serving provider for this call (default 'direct'). One of
                'direct' (Anthropic API), 'vertex' (Claude-on-Vertex), 'google'
                (Gemini AI-Studio), 'vertex-gemini' (Gemini-on-Vertex), 'ollama',
                or 'external'. Powers the per-provider cost A/B (Task 9).
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO llm_calls
            (timestamp, model, input_tokens, output_tokens, cost_usd, latency_ms,
             agent_name, success, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
                agent_name,
                success,
                provider,
            ),
        )

        conn.commit()
        conn.close()

    async def get_daily_summary(self, days_back: int = 0) -> dict:
        """
        Get daily cost summary.

        Args:
            days_back: 0 for today, 1 for yesterday, etc.

        Returns:
            Dict with total_cost, total_calls, calls_per_model, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Calculate the date range
        now = datetime.now(timezone.utc)
        target_date = (now - timedelta(days=days_back)).date()
        start_ts = datetime.combine(
            target_date, datetime.min.time(), tzinfo=timezone.utc
        ).isoformat()
        end_ts = datetime.combine(target_date, datetime.max.time(), tzinfo=timezone.utc).isoformat()

        # Total cost and call count
        cursor.execute(
            "SELECT COUNT(*), SUM(cost_usd) FROM llm_calls WHERE timestamp >= ? AND timestamp <= ?",
            (start_ts, end_ts),
        )
        total_calls, total_cost = cursor.fetchone()
        total_cost = total_cost or 0.0
        total_calls = total_calls or 0

        # Cost per model
        cursor.execute(
            """
            SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY model
            """,
            (start_ts, end_ts),
        )
        model_stats = {}
        for model, count, input_tok, output_tok, cost in cursor.fetchall():
            model_stats[model] = {
                "calls": count,
                "input_tokens": input_tok or 0,
                "output_tokens": output_tok or 0,
                "cost_usd": cost or 0.0,
            }

        # Cost per agent
        cursor.execute(
            """
            SELECT agent_name, COUNT(*), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY agent_name
            """,
            (start_ts, end_ts),
        )
        agent_stats = {}
        for agent, count, cost in cursor.fetchall():
            agent_stats[agent] = {"calls": count, "cost_usd": cost or 0.0}

        # Cost per provider (direct vs Vertex vs Gemini — the Task 9 A/B view)
        cursor.execute(
            """
            SELECT provider, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY provider
            """,
            (start_ts, end_ts),
        )
        provider_stats = {}
        for provider, count, input_tok, output_tok, cost in cursor.fetchall():
            provider_stats[provider or "direct"] = {
                "calls": count,
                "input_tokens": input_tok or 0,
                "output_tokens": output_tok or 0,
                "cost_usd": round(cost or 0.0, 4),
            }

        # Success rate
        cursor.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp <= ?
            """,
            (start_ts, end_ts),
        )
        total, successful = cursor.fetchone()
        success_rate = (successful or 0) / max(total or 1, 1)

        # Average latency
        cursor.execute(
            "SELECT AVG(latency_ms) FROM llm_calls WHERE timestamp >= ? AND timestamp <= ?",
            (start_ts, end_ts),
        )
        avg_latency = cursor.fetchone()[0] or 0

        conn.close()

        return {
            "date": target_date.isoformat(),
            "total_calls": total_calls,
            "total_cost_usd": round(total_cost, 4),
            "success_rate": round(success_rate, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "per_model": model_stats,
            "per_agent": agent_stats,
            "per_provider": provider_stats,
        }

    async def get_monthly_summary(self, months_back: int = 0) -> dict:
        """
        Get monthly cost summary.

        Args:
            months_back: 0 for current month, 1 for last month, etc.

        Returns:
            Dict with total_cost, total_calls, daily_breakdown, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Calculate the date range
        now = datetime.now(timezone.utc)
        # Normalise to midnight so the range covers the full first day of the month.
        first_day_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if months_back == 0:
            # Current month
            month_start = first_day_this_month
        else:
            # Previous months
            for _ in range(months_back):
                first_day_this_month = first_day_this_month - timedelta(days=1)
                first_day_this_month = first_day_this_month.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
            month_start = first_day_this_month

        # Next month (exclusive)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)

        month_start_ts = month_start.isoformat()
        month_end_ts = month_end.isoformat()

        # Total for month
        cursor.execute(
            "SELECT COUNT(*), SUM(cost_usd) FROM llm_calls WHERE timestamp >= ? AND timestamp < ?",
            (month_start_ts, month_end_ts),
        )
        total_calls, total_cost = cursor.fetchone()
        total_cost = total_cost or 0.0
        total_calls = total_calls or 0

        # Daily breakdown
        cursor.execute(
            """
            SELECT DATE(timestamp) as date, COUNT(*), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY DATE(timestamp)
            ORDER BY date ASC
            """,
            (month_start_ts, month_end_ts),
        )
        daily_breakdown = []
        for date, count, cost in cursor.fetchall():
            daily_breakdown.append(
                {
                    "date": date,
                    "calls": count,
                    "cost_usd": round(cost or 0.0, 4),
                }
            )

        # Per-model cost
        cursor.execute(
            """
            SELECT model, COUNT(*), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY model
            """,
            (month_start_ts, month_end_ts),
        )
        per_model = {}
        for model, count, cost in cursor.fetchall():
            per_model[model] = {"calls": count, "cost_usd": round(cost or 0.0, 4)}

        # Per-provider cost (direct vs Vertex vs Gemini — the Task 9 A/B view)
        cursor.execute(
            """
            SELECT provider, COUNT(*), SUM(cost_usd)
            FROM llm_calls
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY provider
            """,
            (month_start_ts, month_end_ts),
        )
        per_provider = {}
        for provider, count, cost in cursor.fetchall():
            per_provider[provider or "direct"] = {
                "calls": count,
                "cost_usd": round(cost or 0.0, 4),
            }

        conn.close()

        return {
            "year_month": month_start.strftime("%Y-%m"),
            "total_calls": total_calls,
            "total_cost_usd": round(total_cost, 4),
            "daily_breakdown": daily_breakdown,
            "per_model": per_model,
            "per_provider": per_provider,
        }

    async def close(self):
        """Close database connection (placeholder for future async ops)."""
        pass
