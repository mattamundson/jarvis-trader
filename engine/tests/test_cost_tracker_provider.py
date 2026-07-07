"""Task 9: per-provider cost tagging in CostTracker.

Verifies the additive `provider` column, the backward-safe migration of a
legacy database (no provider column), the optional `log_call(provider=...)`
argument, and the per_provider breakdown in the daily/monthly summaries. All
tests use temp databases, so they never touch the live llm_costs.db and need
no network or credentials. pytest runs asyncio in auto mode.
"""

import sqlite3
from datetime import datetime, timezone

from llm.cost_tracker import CostTracker


def _cols(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()}
    finally:
        conn.close()


def test_fresh_db_has_provider_column(tmp_path):
    db = str(tmp_path / "costs.db")
    CostTracker(db_path=db)
    assert "provider" in _cols(db)


def test_migration_adds_provider_to_legacy_db(tmp_path):
    db = str(tmp_path / "legacy.db")
    # Build a pre-Task-9 schema (no provider column) with one existing row.
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            latency_ms INTEGER DEFAULT 0,
            agent_name TEXT DEFAULT 'unknown',
            success BOOLEAN DEFAULT 1
        )
        """
    )
    conn.execute(
        "INSERT INTO llm_calls (timestamp, model) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(), "claude-sonnet-4-6"),
    )
    conn.commit()
    conn.close()

    assert "provider" not in _cols(db)
    # Instantiating the tracker runs the additive migration.
    CostTracker(db_path=db)
    assert "provider" in _cols(db)
    # The pre-existing row is backfilled with the 'direct' default, not lost.
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT provider FROM llm_calls").fetchall()
    conn.close()
    assert rows == [("direct",)]


async def test_log_call_defaults_to_direct(tmp_path):
    db = str(tmp_path / "costs.db")
    tracker = CostTracker(db_path=db)
    await tracker.log_call(
        timestamp=datetime.now(timezone.utc).isoformat(),
        model="claude-sonnet-4-6",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.01,
        latency_ms=42,
        agent_name="trader",
        success=True,
    )
    conn = sqlite3.connect(db)
    (provider,) = conn.execute("SELECT provider FROM llm_calls").fetchone()
    conn.close()
    assert provider == "direct"


async def test_log_call_records_explicit_provider(tmp_path):
    db = str(tmp_path / "costs.db")
    tracker = CostTracker(db_path=db)
    await tracker.log_call(
        timestamp=datetime.now(timezone.utc).isoformat(),
        model="claude-sonnet-4-5@20250929",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.01,
        latency_ms=42,
        agent_name="trader",
        success=True,
        provider="vertex",
    )
    conn = sqlite3.connect(db)
    (provider,) = conn.execute("SELECT provider FROM llm_calls").fetchone()
    conn.close()
    assert provider == "vertex"


async def test_daily_summary_breaks_down_by_provider(tmp_path):
    db = str(tmp_path / "costs.db")
    tracker = CostTracker(db_path=db)
    ts = datetime.now(timezone.utc).isoformat()
    await tracker.log_call(
        timestamp=ts, model="m", input_tokens=10, output_tokens=2,
        cost_usd=0.02, latency_ms=1, agent_name="a", success=True, provider="direct",
    )
    await tracker.log_call(
        timestamp=ts, model="m", input_tokens=20, output_tokens=4,
        cost_usd=0.05, latency_ms=1, agent_name="a", success=True, provider="vertex",
    )
    await tracker.log_call(
        timestamp=ts, model="m", input_tokens=30, output_tokens=6,
        cost_usd=0.07, latency_ms=1, agent_name="a", success=True, provider="vertex",
    )

    summary = await tracker.get_daily_summary()
    pp = summary["per_provider"]
    assert pp["direct"]["calls"] == 1
    assert pp["vertex"]["calls"] == 2
    assert pp["vertex"]["input_tokens"] == 50
    assert round(pp["vertex"]["cost_usd"], 4) == 0.12


async def test_monthly_summary_breaks_down_by_provider(tmp_path):
    db = str(tmp_path / "costs.db")
    tracker = CostTracker(db_path=db)
    ts = datetime.now(timezone.utc).isoformat()
    await tracker.log_call(
        timestamp=ts, model="m", input_tokens=1, output_tokens=1,
        cost_usd=0.10, latency_ms=1, agent_name="a", success=True, provider="vertex-gemini",
    )
    summary = await tracker.get_monthly_summary()
    assert summary["per_provider"]["vertex-gemini"]["calls"] == 1
    assert round(summary["per_provider"]["vertex-gemini"]["cost_usd"], 4) == 0.10
