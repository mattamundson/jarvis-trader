"""
Tests for journal_review_router — stats, breakdown, analyze, formalize, monthly.
Uses an in-memory SQLite DB seeded with synthetic paper_trades + trade_journal rows.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.journal_review_router import (
    _compute_breakdown,
    _compute_stats,
    inject_dependencies,
    router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_db(db_path: str, n_wins: int = 6, n_losses: int = 4) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                entry_price REAL NOT NULL,
                exit_price REAL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                pnl REAL,
                status TEXT NOT NULL DEFAULT 'open',
                regime TEXT,
                bias TEXT,
                composite_score REAL,
                stop_loss REAL,
                risk_pct_used REAL,
                notes TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                note TEXT DEFAULT '',
                tags TEXT,
                mood TEXT,
                lesson TEXT
            )
            """
        )

        for i in range(n_wins):
            conn.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"win-{i}",
                    "MES",
                    "buy",
                    1,
                    4000.0 + i,
                    4010.0 + i,
                    f"2026-01-{i+1:02d}T10:00:00Z",
                    f"2026-01-{i+1:02d}T14:00:00Z",
                    50.0,
                    "closed",
                    "BULLISH_CONFIRMED",
                    "bullish",
                    0.75,
                    3990.0,
                    0.01,
                    "clean entry",
                ),
            )
            conn.execute(
                "INSERT INTO trade_journal VALUES (NULL,?,?,?,?,?,?)",
                (f"win-{i}", f"2026-01-{i+1:02d}T14:01:00Z", "held the trade", "good_setup", "confident", "patience paid off"),
            )

        for i in range(n_losses):
            conn.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"loss-{i}",
                    "MGC",
                    "sell",
                    1,
                    2000.0 + i,
                    2020.0 + i,
                    f"2026-01-{i+15:02d}T10:00:00Z",
                    f"2026-01-{i+15:02d}T12:00:00Z",
                    -40.0,
                    "closed",
                    "BEARISH_CONFIRMED",
                    "bearish",
                    0.60,
                    2010.0,
                    0.01,
                    "stopped out",
                ),
            )
            conn.execute(
                "INSERT INTO trade_journal VALUES (NULL,?,?,?,?,?,?)",
                (f"loss-{i}", f"2026-01-{i+15:02d}T12:01:00Z", "FOMO entry", "bad_setup", "frustrated", "waited too long"),
            )
        conn.commit()


@pytest.fixture
def db_file():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    _seed_db(path)
    yield path
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows holds sqlite3 file open briefly after asyncio.to_thread returns


@pytest.fixture
def client(db_file):
    inject_dependencies(db_path=db_file, llm=None)
    app = FastAPI()
    app.include_router(router, prefix="/journal")
    return TestClient(app)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    result = MagicMock()
    result.success = True
    result.content = "## Emotional Patterns\nFOMO entries correlate with losses.\n\n## Trade Duration\nWinners held 4h, losers 2h.\n\n## Best and Worst Conditions\nBest: MES bull. Worst: MGC bear short.\n\n## Behavioral Red Flags\n1. FOMO on loss trades.\n\n## One Rule to Add Now\nNo shorts when regime is BEARISH but Corey is neutral."
    result.error = None
    llm.call = AsyncMock(return_value=result)
    return llm


# ---------------------------------------------------------------------------
# Unit tests — pure functions (no FastAPI)
# ---------------------------------------------------------------------------


class TestComputeStats:
    def test_empty_returns_insufficient(self):
        stats = _compute_stats([])
        assert stats.total_trades == 0
        assert stats.diagnosis == "insufficient_data"

    def test_basic_stats(self):
        trades = [
            {"pnl": 50.0, "exit_time": "2026-01-01T12:00:00Z"},
            {"pnl": 50.0, "exit_time": "2026-01-08T12:00:00Z"},
            {"pnl": -40.0, "exit_time": "2026-01-15T12:00:00Z"},
            {"pnl": -40.0, "exit_time": "2026-01-22T12:00:00Z"},
            {"pnl": 50.0, "exit_time": "2026-01-29T12:00:00Z"},
        ]
        stats = _compute_stats(trades)
        assert stats.total_trades == 5
        assert stats.win_rate == pytest.approx(0.6, abs=0.01)
        assert stats.avg_win_usd == pytest.approx(50.0)
        assert stats.avg_loss_usd == pytest.approx(40.0)
        assert stats.risk_reward_ratio == pytest.approx(50 / 40, abs=0.01)

    def test_diagnosis_win_rate(self):
        trades = [{"pnl": 10.0, "exit_time": "2026-01-01T00:00:00Z"}] * 2 + [
            {"pnl": -5.0, "exit_time": "2026-01-02T00:00:00Z"}
        ] * 8
        assert _compute_stats(trades).diagnosis == "win_rate"

    def test_diagnosis_avg_loss(self):
        trades = [{"pnl": 10.0, "exit_time": "2026-01-01T00:00:00Z"}] * 5 + [
            {"pnl": -15.0, "exit_time": "2026-01-02T00:00:00Z"}
        ] * 5
        stats = _compute_stats(trades)
        assert stats.diagnosis == "avg_loss"

    def test_diagnosis_solid(self):
        trades = [{"pnl": 50.0, "exit_time": "2026-01-01T00:00:00Z"}] * 7 + [
            {"pnl": -20.0, "exit_time": "2026-01-02T00:00:00Z"}
        ] * 3
        stats = _compute_stats(trades)
        assert stats.diagnosis == "solid"

    def test_ev_sign(self):
        trades = [{"pnl": 100.0, "exit_time": None}] * 5 + [
            {"pnl": -200.0, "exit_time": None}
        ] * 5
        stats = _compute_stats(trades)
        assert stats.expected_value_usd < 0


class TestComputeBreakdown:
    def test_symbol_groups(self):
        trades = [
            {"symbol": "MES", "side": "buy", "regime": "BULL", "bias": "bullish", "pnl": 50.0},
            {"symbol": "MES", "side": "buy", "regime": "BULL", "bias": "bullish", "pnl": 50.0},
            {"symbol": "MGC", "side": "sell", "regime": "BEAR", "bias": "bearish", "pnl": -40.0},
        ]
        bd = _compute_breakdown(trades)
        syms = {r.group_value: r for r in bd.by_symbol}
        assert "MES" in syms
        assert "MGC" in syms
        assert syms["MES"].net_pnl == pytest.approx(100.0)

    def test_flagging_threshold(self):
        # 5+ trades with WR > 55%: should be flagged
        trades = [{"symbol": "MES", "side": "buy", "regime": "B", "bias": "b", "pnl": 50.0}] * 6 + [
            {"symbol": "MES", "side": "buy", "regime": "B", "bias": "b", "pnl": -10.0}
        ] * 1
        bd = _compute_breakdown(trades)
        flags = {r.group_value for r in bd.flags}
        assert "MES" in flags

    def test_no_flag_below_5(self):
        trades = [{"symbol": "MES", "side": "buy", "regime": "B", "bias": "b", "pnl": 50.0}] * 3
        bd = _compute_breakdown(trades)
        assert len(bd.flags) == 0


# ---------------------------------------------------------------------------
# Integration tests — HTTP endpoints
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    def test_returns_stats(self, client):
        resp = client.get("/journal/review/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_trades"] == 10
        assert body["win_rate"] == pytest.approx(0.6, abs=0.01)

    def test_limit_param(self, client):
        resp = client.get("/journal/review/stats?limit=6")
        assert resp.status_code == 200
        assert resp.json()["total_trades"] <= 6

    def test_below_min_limit(self, client):
        resp = client.get("/journal/review/stats?limit=2")
        assert resp.status_code == 422


class TestBreakdownEndpoint:
    def test_returns_all_groups(self, client):
        resp = client.get("/journal/review/breakdown")
        assert resp.status_code == 200
        body = resp.json()
        assert "by_symbol" in body
        assert "by_side" in body
        assert "by_regime" in body
        assert "by_bias" in body
        assert "flags" in body

    def test_symbol_values_present(self, client):
        resp = client.get("/journal/review/breakdown")
        syms = {r["group_value"] for r in resp.json()["by_symbol"]}
        assert "MES" in syms
        assert "MGC" in syms


class TestAnalyzeEndpoint:
    def test_no_llm_returns_503(self, db_file):
        inject_dependencies(db_path=db_file, llm=None)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.post("/journal/review/analyze", json={"limit": 10})
        assert resp.status_code == 503

    def test_with_llm(self, db_file, mock_llm):
        inject_dependencies(db_path=db_file, llm=mock_llm)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.post("/journal/review/analyze", json={"limit": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert "analysis" in body
        assert body["trade_count"] == 10
        assert body["has_journal_data"] is True


class TestFormalizeEndpoint:
    def test_empty_observation_422(self, db_file):
        inject_dependencies(db_path=db_file, llm=None)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.post("/journal/review/formalize", json={"observation": "   "})
        assert resp.status_code == 422

    def test_no_llm_503(self, db_file):
        inject_dependencies(db_path=db_file, llm=None)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.post("/journal/review/formalize", json={"observation": "I win more on MES longs"})
        assert resp.status_code == 503

    def test_with_llm_valid_json(self, db_file, mock_llm):
        json_payload = json.dumps({
            "pressure_tested": "Sample size is small but consistent.",
            "falsifiable_rule": "Only take MES longs in BULLISH_CONFIRMED regime.",
            "journal_columns": ["regime", "side"],
            "sample_size": 30,
            "pass_threshold": "WR >= 60% after 30 trades",
            "fail_threshold": "WR < 45% after 30 trades",
            "abandonment_criteria": "Two consecutive losing months",
        })
        mock_llm.call = AsyncMock(
            return_value=MagicMock(success=True, content=json_payload, error=None)
        )
        inject_dependencies(db_path=db_file, llm=mock_llm)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.post("/journal/review/formalize", json={"observation": "I win more on MES longs"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["falsifiable_rule"] != ""
        assert body["sample_size"] == 30
        assert "regime" in body["journal_columns"]


class TestMonthlyEndpoint:
    def test_without_llm(self, client):
        resp = client.get("/journal/review/monthly")
        assert resp.status_code == 200
        body = resp.json()
        assert "stats" in body
        assert "breakdown" in body
        assert "llm_analysis" in body
        assert body["trade_count"] == 10

    def test_with_llm(self, db_file, mock_llm):
        inject_dependencies(db_path=db_file, llm=mock_llm)
        app = FastAPI()
        app.include_router(router, prefix="/journal")
        c = TestClient(app)
        resp = c.get("/journal/review/monthly")
        assert resp.status_code == 200
        body = resp.json()
        assert "Emotional Patterns" in body["llm_analysis"]
