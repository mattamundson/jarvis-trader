"""T4: persistent LLM spend tracking.

Verifies:
- CostTracker relative db_path anchoring (CWD-independent — the "/llm/stats
  resets on restart" root cause).
- Daily/monthly rollup series + all-time totals.
- Fire-once-per-period threshold alerts (env-configurable).
- JarvisLLMClient.run-context wiring: successful calls inside a pipeline run
  context persist into pipeline_llm_costs via db_manager.
- /llm/stats/rollup and /llm/stats responses carry historical totals + alerts.

All tests use temp databases; they never touch the live llm_costs.db or
jarvis_trader.db and need no network or credentials.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from llm.cost_tracker import CostTracker, _resolve_db_path


def _cols(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


# ── path anchoring ─────────────────────────────────────────────────────────


def test_relative_db_path_anchored_to_engine(tmp_path, monkeypatch):
    """A relative 'data/llm_costs.db' must resolve under the engine dir, not CWD."""
    monkeypatch.delenv("JARVIS_LLM_COST_DB", raising=False)
    resolved = _resolve_db_path("data/llm_costs.db")
    assert resolved.endswith(os.path.join("engine", "data", "llm_costs.db")) or resolved.endswith(
        "engine\\data\\llm_costs.db"
    )
    assert os.path.isabs(resolved)


def test_absolute_db_path_passthrough(tmp_path):
    """Absolute paths (tests, tmp dirs) must pass through untouched."""
    p = str(tmp_path / "costs.db")
    assert _resolve_db_path(p) == p


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LLM_COST_DB", str(tmp_path / "override.db"))
    assert _resolve_db_path("data/llm_costs.db") == str(tmp_path / "override.db")


def test_fresh_db_has_alert_table(tmp_path):
    db = str(tmp_path / "costs.db")
    CostTracker(db_path=db)
    conn = sqlite3.connect(db)
    try:
        names = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "llm_alert_fired" in names


# ── rollups + totals ───────────────────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path):
    return CostTracker(db_path=str(tmp_path / "costs.db"))


async def test_daily_rollup_zero_filled_and_totals(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    # Two calls today; one call two days ago.
    now = datetime.now(timezone.utc)
    ts_now = now.isoformat()
    ts_2d = (now - timedelta(days=2)).isoformat()
    for ts, cost in [(ts_now, 0.50), (ts_now, 0.60), (ts_2d, 0.10)]:
        await t.log_call(
            timestamp=ts, model="m", input_tokens=10, output_tokens=2,
            cost_usd=cost, latency_ms=1, agent_name="a", success=True,
        )
    daily = await t.get_daily_rollup(days=7)
    assert len(daily) == 7
    assert daily[-1]["calls"] == 2
    assert round(daily[-1]["cost_usd"], 4) == 1.10
    assert daily[-3]["calls"] == 1  # two days back
    assert daily[-3]["cost_usd"] == 0.10
    # Earlier days zero-filled
    assert daily[0]["calls"] == 0 and daily[0]["cost_usd"] == 0.0


async def test_monthly_rollup_zero_filled(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=0.25, latency_ms=1, agent_name="a", success=True,
    )
    monthly = await t.get_monthly_rollup(months=3)
    assert len(monthly) == 3
    assert monthly[-1]["year_month"] == now.strftime("%Y-%m")
    assert monthly[-1]["calls"] == 1
    assert round(monthly[-1]["cost_usd"], 4) == 0.25
    assert monthly[0]["calls"] == 0


async def test_all_time_totals(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=100, output_tokens=50,
        cost_usd=1.25, latency_ms=1, agent_name="a", success=True,
    )
    totals = await t.get_all_time_totals()
    assert totals["calls"] == 1
    assert totals["cost_usd"] == 1.25
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 50


# ── threshold alerts (fire-once per period) ────────────────────────────────


async def test_threshold_fires_once_per_period(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=2.00, latency_ms=1, agent_name="a", success=True,
    )
    # Threshold 1.0 — both daily + monthly fire (2.00 > 1.0).
    fired = await t.check_thresholds(daily_alert_usd=1.0, monthly_alert_usd=1.0)
    assert {f["alert_type"] for f in fired} == {"daily", "monthly"}
    # Second call with more spend must NOT re-fire the same period.
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=3.00, latency_ms=1, agent_name="a", success=True,
    )
    fired2 = await t.check_thresholds(daily_alert_usd=1.0, monthly_alert_usd=1.0)
    assert fired2 == []


async def test_threshold_zero_disables_alert(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=9.99, latency_ms=1, agent_name="a", success=True,
    )
    fired = await t.check_thresholds(daily_alert_usd=0, monthly_alert_usd=0)
    assert fired == []


async def test_threshold_below_limit_no_fire(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=0.05, latency_ms=1, agent_name="a", success=True,
    )
    fired = await t.check_thresholds(daily_alert_usd=100.0, monthly_alert_usd=100.0)
    assert fired == []


async def test_alert_state_reports_config_and_fired(tmp_path):
    db = str(tmp_path / "costs.db")
    t = CostTracker(db_path=db)
    now = datetime.now(timezone.utc)
    await t.log_call(
        timestamp=now.isoformat(), model="m", input_tokens=1, output_tokens=1,
        cost_usd=5.50, latency_ms=1, agent_name="a", success=True,
    )
    await t.check_thresholds(daily_alert_usd=1.0, monthly_alert_usd=1.0)
    state = await t.get_alert_state()
    assert state["daily_alert_usd"] > 0
    assert state["monthly_alert_usd"] > 0
    assert len(state["recent_fired"]) == 2


# ── client run-context persistence into pipeline_llm_costs ─────────────────


def _make_db_manager(tmp_path):
    from database.manager import DatabaseManager

    dm = DatabaseManager(db_path=str(tmp_path / "jt.db"))
    dm.initialize()
    return dm


async def test_client_persists_pipeline_cost_with_run_context(tmp_path):
    import time as _time
    from types import SimpleNamespace

    from llm.client import JarvisLLMClient, clear_llm_run_context, set_llm_run_context

    dm = _make_db_manager(tmp_path)
    client = JarvisLLMClient(
        api_key="k", db_path=str(tmp_path / "costs.db"), db_manager=dm
    )
    set_llm_run_context("run_abc123", "MES")
    try:
        result = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
            content=[SimpleNamespace(text="ok")],
        )
        await client._handle_success(
            result=result,
            current_model="claude-sonnet-4-6",
            start_time=_time.time(),
            retries=0,
            agent_name="technical_analyst",
        )
    finally:
        clear_llm_run_context()

    conn = sqlite3.connect(str(tmp_path / "jt.db"))
    try:
        row = conn.execute(
            "SELECT run_id, symbol, stage, model, input_tokens, output_tokens "
            "FROM pipeline_llm_costs"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "run_abc123"
    assert row[1] == "MES"
    assert row[2] == "technical_analyst"
    assert row[3] == "claude-sonnet-4-6"
    assert row[4] == 100
    assert row[5] == 50


async def test_client_no_run_context_skips_pipeline_table(tmp_path):
    import time as _time
    from types import SimpleNamespace

    from llm.client import JarvisLLMClient, clear_llm_run_context

    dm = _make_db_manager(tmp_path)
    client = JarvisLLMClient(
        api_key="k", db_path=str(tmp_path / "costs.db"), db_manager=dm
    )
    clear_llm_run_context()
    result = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        content=[SimpleNamespace(text="ok")],
    )
    await client._handle_success(
        result=result,
        current_model="claude-sonnet-4-6",
        start_time=_time.time(),
        retries=0,
        agent_name="technical_analyst",
    )
    conn = sqlite3.connect(str(tmp_path / "jt.db"))
    try:
        n = conn.execute("SELECT COUNT(*) FROM pipeline_llm_costs").fetchone()[0]
    finally:
        conn.close()
    assert n == 0
