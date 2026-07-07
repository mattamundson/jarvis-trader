"""
HTTP integration tests for the Brier/IC calibration diagnostics endpoint
added in analytics_router.py.

Exercises GET /analytics/calibration under three states:
  * cold: empty trade_outcomes → neutral Brier, zero IC, ready_to_activate=False
  * partial: some agents have samples, others don't
  * warm: all agents at or above min_trades → ready_to_activate=True
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# Mirrors AGENT_NAMES in engine/analytics/agent_feedback.py (7 agents post Phase 3).
_TEST_AGENTS = ("technical", "news", "social", "fundamental", "corey", "breakout", "harmonic")


def _init_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # Schema mirrors AgentFeedbackTracker._init_db post 2026-04-25 migration:
        # 7 *_signal columns + regime, keeping cold-start parity with production.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_outcomes (
                trade_id TEXT PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                direction TEXT,
                pnl_usd REAL,
                pnl_pct REAL,
                outcome TEXT,
                technical_signal REAL,
                news_signal REAL,
                social_signal REAL,
                fundamental_signal REAL,
                corey_signal REAL,
                breakout_signal REAL,
                harmonic_signal REAL,
                regime TEXT
            )
        """
        )


def _seed_rows(db_path: Path, agent_idx: int, n: int, now_iso: str | None = None):
    """Seed n rows where only the given agent column has a non-zero signal.

    agent_idx must be in [0, len(_TEST_AGENTS)).
    """
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()
    if not (0 <= agent_idx < len(_TEST_AGENTS)):
        raise ValueError(f"agent_idx {agent_idx} out of range; expected 0..{len(_TEST_AGENTS) - 1}")
    cols = [0.0] * len(_TEST_AGENTS)
    with sqlite3.connect(db_path) as conn:
        for i in range(n):
            sigs = list(cols)
            sigs[agent_idx] = 0.7
            conn.execute(
                "INSERT OR REPLACE INTO trade_outcomes "
                "(trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome, "
                " technical_signal, news_signal, social_signal, fundamental_signal, corey_signal, "
                " breakout_signal, harmonic_signal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"t{agent_idx}_{i}",
                    now_iso,
                    "MCL",
                    "LONG",
                    10.0,
                    0.0,
                    "WIN",
                    *sigs,
                ),
            )


@pytest.fixture
def client_with_db(tmp_path, monkeypatch):
    """Build a TestClient with the calibration DB redirected to a temp file."""
    db_path = tmp_path / "agent_feedback.db"
    _init_schema(db_path)

    # Patch both import paths — router imports via `analytics.*`, but the
    # debate module (loaded by _is_brier_enabled() indirectly) may use the
    # `engine.*` path. Patch both to be safe.
    import engine.analytics.agent_feedback as af_eng
    import engine.analytics.ic_ensemble as ic_eng

    import analytics.agent_feedback as af_short
    import analytics.ic_ensemble as ic_short

    monkeypatch.setattr(af_short, "DB_PATH", db_path)
    monkeypatch.setattr(af_eng, "DB_PATH", db_path)
    monkeypatch.setattr(ic_short, "_DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(ic_eng, "_DEFAULT_DB_PATH", db_path)

    # Force re-import of the router so @router.get decorators pick up patches
    for key in list(sys.modules.keys()):
        if "analytics_router" in key:
            del sys.modules[key]

    from routers.analytics_router import router as analytics_router

    app = FastAPI()
    app.include_router(analytics_router)
    return TestClient(app, raise_server_exceptions=True), db_path


def test_calibration_cold_db_returns_neutral(client_with_db):
    """Empty trade_outcomes → every agent neutral, ready_to_activate=False."""
    client, _ = client_with_db
    resp = client.get("/analytics/calibration")
    assert resp.status_code == 200
    data = resp.json()

    # Shape
    assert set(data.keys()) >= {
        "brier_enabled",
        "brier_blend_alpha",
        "min_trades_threshold",
        "window_days",
        "agents",
        "per_agent",
        "total_outcomes",
        "ready_to_activate",
        "neutral_sentinel",
        "timestamp",
    }
    # Cold state
    assert data["total_outcomes"] == 0
    assert data["ready_to_activate"] is False
    assert data["active_agents"] == []
    assert data["blocked_by"] == []
    assert data["rows_excluded_corrupt"] == 0
    assert data["rows_excluded_duplicate"] == 0
    assert data["neutral_sentinel"] == pytest.approx(0.25)
    # All agents present, all sample_counts=0, all brier_score=neutral, ic_score=0
    for agent in _TEST_AGENTS:
        entry = data["per_agent"][agent]
        assert entry["sample_count"] == 0
        assert entry["ready"] is False
        assert entry["ic_score"] == pytest.approx(0.0)
        assert entry["brier_score"] == pytest.approx(0.25)


def test_calibration_single_active_agent_is_ready(client_with_db):
    """W6 honest gate: when only technical emits signals (>= min_trades) and the
    other agents are silent, readiness is True - perennially-silent agents no
    longer block activation. active_agents lists technical; blocked_by is empty.
    """
    client, db_path = client_with_db
    _seed_rows(db_path, agent_idx=0, n=6)  # technical only, 6 rows (>= min_trades=5)

    data = client.get("/analytics/calibration").json()
    assert data["total_outcomes"] == 6
    assert data["per_agent"]["technical"]["sample_count"] == 6
    assert data["per_agent"]["technical"]["ready"] is True
    assert data["per_agent"]["news"]["sample_count"] == 0
    assert data["active_agents"] == ["technical"]
    assert data["blocked_by"] == []
    assert data["ready_to_activate"] is True


def test_calibration_active_agent_below_floor_blocks(client_with_db):
    """W6: an agent that emits signals but sits below min_trades blocks readiness
    and appears in blocked_by."""
    client, db_path = client_with_db
    _seed_rows(db_path, agent_idx=0, n=6)  # technical ready
    _seed_rows(db_path, agent_idx=1, n=2)  # news active but below floor (2 < 5)

    data = client.get("/analytics/calibration").json()
    assert "news" in data["blocked_by"]
    assert "technical" not in data["blocked_by"]
    assert set(data["active_agents"]) == {"technical", "news"}
    assert data["ready_to_activate"] is False


def test_calibration_reports_integrity_exclusions(client_with_db):
    """W5: corrupt-magnitude and logical-duplicate rows are surfaced via the
    rows_excluded_* fields."""
    client, db_path = client_with_db
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trade_outcomes "
            "(trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome, technical_signal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("corrupt", now, "MES", "LONG", 10102.98, 0.0, "WIN", 0.9),
        )
        for k in range(2):
            conn.execute(
                "INSERT OR REPLACE INTO trade_outcomes "
                "(trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome, technical_signal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"dup{k}", now, "MES", "SHORT", -20.0, 0.0, "LOSS", 0.9),
            )

    data = client.get("/analytics/calibration").json()
    assert data["rows_excluded_corrupt"] >= 1
    assert data["rows_excluded_duplicate"] >= 1


def test_calibration_full_warmup_sets_ready_flag(client_with_db):
    """All 7 agents above min_trades → ready_to_activate=True.

    Phase 3 (2026-04-25) extended AGENT_NAMES from 5 to 7 — added `breakout`
    and `harmonic`. The endpoint requires *all* tracked agents to have
    sample_count >= MIN_TRADES_FOR_IC before flipping ready_to_activate=True,
    so the fixture must seed all 7.
    """
    client, db_path = client_with_db
    n_agents = len(_TEST_AGENTS)
    for i in range(n_agents):
        _seed_rows(db_path, agent_idx=i, n=5)  # 5 rows per agent

    data = client.get("/analytics/calibration").json()
    assert data["total_outcomes"] == 5 * n_agents
    assert data["ready_to_activate"] is True
    for agent in _TEST_AGENTS:
        entry = data["per_agent"][agent]
        assert entry["sample_count"] == 5
        assert entry["ready"] is True


def test_calibration_reflects_env_gate(monkeypatch, client_with_db):
    """brier_enabled field must mirror BRIER_CALIBRATION_ENABLED env var."""
    client, _ = client_with_db

    monkeypatch.delenv("BRIER_CALIBRATION_ENABLED", raising=False)
    off_data = client.get("/analytics/calibration").json()
    assert off_data["brier_enabled"] is False

    monkeypatch.setenv("BRIER_CALIBRATION_ENABLED", "true")
    on_data = client.get("/analytics/calibration").json()
    assert on_data["brier_enabled"] is True
