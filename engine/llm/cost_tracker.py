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
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Alert thresholds (env-configurable) ────────────────────────────────────
# Fired once per period (day / calendar month, UTC) when spend crosses the
# threshold. Persisted in llm_alert_fired so restarts don't re-fire.
LLM_COST_DAILY_ALERT_USD = float(os.getenv("LLM_COST_DAILY_ALERT_USD", "5.0"))
LLM_COST_MONTHLY_ALERT_USD = float(os.getenv("LLM_COST_MONTHLY_ALERT_USD", "25.0"))


def _resolve_db_path(db_path: str) -> str:
    """Anchor a relative db_path to the engine dir regardless of CWD.

    The engine is launched from engine/ under pm2 but from the repo root by
    some scripts; a bare relative path like "data/llm_costs.db" resolves to
    different files in each case, which made /llm/stats appear to reset on
    restart. Absolute paths (tests, tmp dirs) and Unix-style /tmp paths pass
    through untouched. Honors JARVIS_LLM_COST_DB as an explicit override.
    """
    override = os.getenv("JARVIS_LLM_COST_DB", "").strip()
    if override:
        db_path = override
    if os.path.isabs(db_path) or db_path.startswith("/") or ":" in db_path[:2]:
        return db_path
    # engine/llm/cost_tracker.py -> engine/
    return str(Path(__file__).resolve().parent.parent / db_path)


class CostTracker:
    """SQLite-backed LLM cost and usage tracker."""

    def __init__(self, db_path: str = "data/llm_costs.db"):
        """
        Initialize the cost tracker.

        Args:
            db_path: Path to SQLite database file (relative paths are anchored
                to the engine directory; JARVIS_LLM_COST_DB overrides)
        """
        self.db_path = _resolve_db_path(db_path)
        self._init_db()
        logger.info(f"✅ CostTracker initialized at {self.db_path}")

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
<<<<<<< HEAD
=======

        # T4: once-per-period alert state. period_key like 'daily:2026-08-18'
        # or 'monthly:2026-08'; a row means the threshold alert already fired
        # for that period, so restarts / repeated calls don't re-fire.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_alert_fired (
                period_key   TEXT PRIMARY KEY,
                alert_type   TEXT NOT NULL,
                value_usd    REAL NOT NULL,
                threshold_usd REAL NOT NULL,
                fired_at     TEXT NOT NULL
            )
            """
        )
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

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

    async def get_daily_rollup(self, days: int = 30) -> list[dict]:
        """
        Daily spend series for the last ``days`` days (UTC), oldest first.

        Returns a list of dicts: {date, calls, cost_usd, input_tokens,
        output_tokens}. Every day in the window appears (zero-filled), so the
        series is directly plottable.
        """
        days = max(1, min(int(days), 365))
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            start = (now - timedelta(days=days - 1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            cursor.execute(
                """
                SELECT DATE(timestamp) AS d,
                       COUNT(*),
                       COALESCE(SUM(cost_usd), 0.0),
                       COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0)
                FROM llm_calls
                WHERE timestamp >= ?
                GROUP BY DATE(timestamp)
                ORDER BY d ASC
                """,
                (start.isoformat(),),
            )
            by_date = {row[0]: row for row in cursor.fetchall()}
            series = []
            for i in range(days):
                day = (start + timedelta(days=i)).date().isoformat()
                row = by_date.get(day)
                series.append(
                    {
                        "date": day,
                        "calls": int(row[1]) if row else 0,
                        "cost_usd": round(float(row[2]), 4) if row else 0.0,
                        "input_tokens": int(row[3]) if row else 0,
                        "output_tokens": int(row[4]) if row else 0,
                    }
                )
            return series
        finally:
            conn.close()

    async def get_monthly_rollup(self, months: int = 12) -> list[dict]:
        """
        Monthly spend series for the last ``months`` calendar months (UTC).

        Returns a list of dicts: {year_month, calls, cost_usd}. Every month in
        the window appears (zero-filled).
        """
        months = max(1, min(int(months), 60))
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Walk back to the first month in the window
            start_month = first_this_month
            for _ in range(months - 1):
                if start_month.month == 1:
                    start_month = start_month.replace(year=start_month.year - 1, month=12)
                else:
                    start_month = start_month.replace(month=start_month.month - 1)
            cursor.execute(
                """
                SELECT substr(timestamp, 1, 7) AS ym,
                       COUNT(*),
                       COALESCE(SUM(cost_usd), 0.0)
                FROM llm_calls
                WHERE timestamp >= ?
                GROUP BY ym
                ORDER BY ym ASC
                """,
                (start_month.isoformat(),),
            )
            by_month = {row[0]: row for row in cursor.fetchall()}
            series = []
            ym = start_month
            for _ in range(months):
                key = ym.strftime("%Y-%m")
                row = by_month.get(key)
                series.append(
                    {
                        "year_month": key,
                        "calls": int(row[1]) if row else 0,
                        "cost_usd": round(float(row[2]), 4) if row else 0.0,
                    }
                )
                # Advance one calendar month
                if ym.month == 12:
                    ym = ym.replace(year=ym.year + 1, month=1)
                else:
                    ym = ym.replace(month=ym.month + 1)
            return series
        finally:
            conn.close()

    async def get_all_time_totals(self) -> dict:
        """All-time totals: calls, cost_usd, input/output tokens."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(cost_usd), 0.0),
                       COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0)
                FROM llm_calls
                """
            )
            row = cursor.fetchone()
            return {
                "calls": int(row[0]),
                "cost_usd": round(float(row[1]), 4),
                "input_tokens": int(row[2]),
                "output_tokens": int(row[3]),
            }
        finally:
            conn.close()

    async def check_thresholds(
        self,
        daily_alert_usd: float | None = None,
        monthly_alert_usd: float | None = None,
    ) -> list[dict]:
        """
        Fire-once-per-period alerts when spend crosses configured thresholds.

        Args:
            daily_alert_usd: Daily threshold in USD (default from env
                LLM_COST_DAILY_ALERT_USD, default 5.0).
            monthly_alert_usd: Monthly threshold in USD (default from env
                LLM_COST_MONTHLY_ALERT_USD, default 25.0).

        Returns a list of newly fired alert dicts:
            {alert_type, period_key, value_usd, threshold_usd, message}
        A threshold <= 0 disables that alert. Once fired, a period is recorded
        in llm_alert_fired and will not re-fire until the next period.
        """
        daily_alert_usd = (
            LLM_COST_DAILY_ALERT_USD if daily_alert_usd is None else daily_alert_usd
        )
        monthly_alert_usd = (
            LLM_COST_MONTHLY_ALERT_USD if monthly_alert_usd is None else monthly_alert_usd
        )
        now = datetime.now(timezone.utc)
        today_key = now.date().isoformat()
        month_key = now.strftime("%Y-%m")
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE timestamp >= ?",
                (today_start.isoformat(),),
            )
            today_cost = float(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE timestamp >= ?",
                (month_start.isoformat(),),
            )
            month_cost = float(cursor.fetchone()[0])

            fired: list[dict] = []
            candidates = []
            if daily_alert_usd > 0:
                candidates.append(
                    ("daily", f"daily:{today_key}", today_cost, float(daily_alert_usd))
                )
            if monthly_alert_usd > 0:
                candidates.append(
                    ("monthly", f"monthly:{month_key}", month_cost, float(monthly_alert_usd))
                )

            for alert_type, period_key, value, threshold in candidates:
                if value <= threshold:
                    continue
                row = cursor.execute(
                    "SELECT 1 FROM llm_alert_fired WHERE period_key = ?", (period_key,)
                ).fetchone()
                if row:
                    continue
                cursor.execute(
                    "INSERT INTO llm_alert_fired (period_key, alert_type, value_usd, "
                    "threshold_usd, fired_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        period_key,
                        alert_type,
                        round(value, 4),
                        round(threshold, 4),
                        now.isoformat(),
                    ),
                )
                fired.append(
                    {
                        "alert_type": alert_type,
                        "period_key": period_key,
                        "value_usd": round(value, 4),
                        "threshold_usd": round(threshold, 4),
                        "message": (
                            f"LLM {alert_type} spend ${value:.4f} exceeds "
                            f"${threshold:.2f} threshold ({period_key})"
                        ),
                    }
                )
                logger.warning(
                    "[LLM-ALERT] %s spend $%.4f exceeded threshold $%.2f (%s)",
                    alert_type,
                    value,
                    threshold,
                    period_key,
                )
            conn.commit()
            return fired
        finally:
            conn.close()

    async def get_alert_state(self) -> dict:
        """Current threshold config + latest fired alerts (for dashboards)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT period_key, alert_type, value_usd, threshold_usd, fired_at "
                "FROM llm_alert_fired ORDER BY fired_at DESC LIMIT 20"
            )
            fired = [
                {
                    "period_key": r[0],
                    "alert_type": r[1],
                    "value_usd": round(float(r[2]), 4),
                    "threshold_usd": round(float(r[3]), 4),
                    "fired_at": r[4],
                }
                for r in cursor.fetchall()
            ]
            return {
                "daily_alert_usd": LLM_COST_DAILY_ALERT_USD,
                "monthly_alert_usd": LLM_COST_MONTHLY_ALERT_USD,
                "recent_fired": fired,
            }
        finally:
            conn.close()

    async def close(self):
        """Close database connection (placeholder for future async ops)."""
        pass
