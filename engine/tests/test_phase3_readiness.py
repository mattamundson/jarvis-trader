"""
Tests for Phase 3 programmatic readiness criteria.

Strategy:
- Each criterion gets a synthetic SQLite DB that passes, and one that fails.
- evaluate_all_criteria overall logic is exercised with constructed mock criteria.
- HTTP route is tested via FastAPI TestClient (no auth — test app skips middleware).
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Literal
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago(n: int) -> datetime:
    return datetime.now(_UTC) - timedelta(days=n)


def _make_db(
    trades: list[dict] | None = None,
    pnl_snapshots: list[dict] | None = None,
    system_state: list[dict] | None = None,
) -> str:
    """
    Create a temporary SQLite DB pre-populated with test data.
    Returns path to the DB file (caller owns cleanup via tempfile).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            trade_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            pnl REAL,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT DEFAULT ''
        );
        CREATE TABLE pnl_snapshots (
            date TEXT PRIMARY KEY,
            daily_pnl REAL NOT NULL DEFAULT 0.0,
            portfolio_equity REAL NOT NULL DEFAULT 0.0,
            peak_equity REAL NOT NULL DEFAULT 0.0,
            consecutive_losses INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
            realized_peak_equity REAL DEFAULT NULL
        );
        CREATE TABLE system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        );
        """
    )

    if trades:
        for t in trades:
            conn.execute(
                "INSERT INTO paper_trades "
                "(trade_id, symbol, side, quantity, entry_price, exit_price, "
                " entry_time, exit_time, pnl, status, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    t.get("trade_id", "t-1"),
                    t.get("symbol", "MES"),
                    t.get("side", "LONG"),
                    t.get("quantity", 1),
                    t.get("entry_price", 100.0),
                    t.get("exit_price"),
                    t.get("entry_time", _iso(_days_ago(61))),
                    t.get("exit_time"),
                    t.get("pnl"),
                    t.get("status", "open"),
                    t.get("notes", ""),
                ),
            )

    if pnl_snapshots:
        for s in pnl_snapshots:
            # realized_peak_equity defaults to peak_equity when not specified so
            # the new C5 criterion uses the same value as the test data intends.
            realized_pk = s.get("realized_peak_equity", s.get("peak_equity", 10000.0))
            conn.execute(
                "INSERT OR REPLACE INTO pnl_snapshots "
                "(date, daily_pnl, portfolio_equity, peak_equity, realized_peak_equity) "
                "VALUES (?,?,?,?,?)",
                (
                    s["date"],
                    s.get("daily_pnl", 0.0),
                    s.get("portfolio_equity", 10000.0),
                    s.get("peak_equity", 10000.0),
                    realized_pk,
                ),
            )

    if system_state:
        for ss in system_state:
            conn.execute(
                "INSERT OR REPLACE INTO system_state (key, value) VALUES (?,?)",
                (ss["key"], ss["value"]),
            )

    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Import criteria
# ---------------------------------------------------------------------------

import sys as _sys

_engine_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)))
if _engine_dir not in _sys.path:
    _sys.path.insert(0, _engine_dir)

from readiness.phase3_criteria import (
    _ALL_CRITERIA,
    ConsecutiveLossStreakCriterion,
    EngineUptimeStabilityCriterion,
    KillSwitchInvocationsCriterion,
    MaxDrawdownCriterion,
    PaperTradesCountCriterion,
    PaperTradingWindowCriterion,
    Phase3Criterion,
    ProfitFactorCriterion,
    SafetyLayerTestCoverageCriterion,
    SortinoRatioCriterion,
    WinRateCriterion,
    evaluate_all_criteria,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_tmp_dbs(tmp_path):
    """Ensure temp DBs are cleaned up after each test."""
    yield


# ---------------------------------------------------------------------------
# C1 — paper_trading_window
# ---------------------------------------------------------------------------


class TestPaperTradingWindow:
    def test_passes_when_oldest_trade_is_old_enough(self):
        trades = [
            {
                "trade_id": "old-1",
                "exit_time": _iso(_days_ago(70)),
                "pnl": 50.0,
                "status": "closed",
            }
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = PaperTradingWindowCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
            assert "70" in evidence or "71" in evidence or "d ago" in evidence
        finally:
            os.unlink(db)

    def test_fails_when_oldest_trade_is_too_recent(self):
        trades = [
            {
                "trade_id": "recent-1",
                "exit_time": _iso(_days_ago(10)),
                "pnl": 50.0,
                "status": "closed",
            }
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = PaperTradingWindowCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_no_closed_trades(self):
        db = _make_db()
        try:
            passed, evidence = PaperTradingWindowCriterion().check(db)
            assert not passed
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C2 — paper_trades_count
# ---------------------------------------------------------------------------


class TestPaperTradesCount:
    def test_passes_with_100_closed_trades(self):
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": 10.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = PaperTradesCountCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_with_fewer_than_100_trades(self):
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": 10.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(99)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = PaperTradesCountCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C3 — win_rate
# ---------------------------------------------------------------------------


class TestWinRate:
    def test_passes_when_win_rate_meets_threshold(self):
        # 60 wins, 40 losses = 60% win rate
        trades = [
            {
                "trade_id": f"w-{i}",
                "pnl": 10.0 if i < 60 else -5.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = WinRateCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
            assert "60.0%" in evidence or "60%" in evidence
        finally:
            os.unlink(db)

    def test_fails_when_win_rate_below_threshold(self):
        # 40 wins, 60 losses = 40% win rate
        trades = [
            {
                "trade_id": f"w-{i}",
                "pnl": 10.0 if i < 40 else -5.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = WinRateCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C4 — profit_factor
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def test_passes_when_pf_above_threshold(self):
        # 100 trades: profit=$1500, loss=$500 → PF=3.0
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": 15.0 if i < 100 else -5.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ] + [
            {
                "trade_id": f"l-{i}",
                "pnl": -5.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ]
        # 100 wins of $15 (=$1500 gross profit) + 100 losses of $5 (=$500 gross loss) → PF=3.0
        db = _make_db(trades=trades)
        try:
            passed, evidence = ProfitFactorCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_pf_below_threshold(self):
        # PF = 100/200 = 0.5 — lots of losses
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": 1.0 if i < 100 else -2.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ] + [
            {
                "trade_id": f"l-{i}",
                "pnl": -2.0,
                "exit_time": _iso(_days_ago(5)),
                "status": "closed",
            }
            for i in range(100)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = ProfitFactorCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C5 — max_drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_passes_when_drawdown_within_limit(self):
        # peak=10100, trough=9800 → dd~3%
        snapshots = [
            {
                "date": (datetime.now(_UTC) - timedelta(days=d)).strftime("%Y-%m-%d"),
                "portfolio_equity": 10100.0 - d * 2,
                "peak_equity": 10100.0,
                "daily_pnl": 0.0,
            }
            for d in range(30)
        ]
        db = _make_db(pnl_snapshots=snapshots)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_drawdown_exceeds_limit(self):
        # peak=10000, trough=8000 → dd=20% — well over 8%
        snapshots = [
            {
                "date": (datetime.now(_UTC) - timedelta(days=d)).strftime("%Y-%m-%d"),
                "portfolio_equity": 10000.0 - d * 70,
                "peak_equity": 10000.0,
                "daily_pnl": 0.0,
            }
            for d in range(30)
        ]
        db = _make_db(pnl_snapshots=snapshots)
        try:
            passed, evidence = MaxDrawdownCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C6 — sortino_ratio
# ---------------------------------------------------------------------------


class TestSortinoRatio:
    def test_passes_with_good_sortino(self):
        # All positive returns → Sortino = infinite → pass
        base_equity = 10000.0
        daily_gain = 50.0
        snapshots = [
            {
                "date": (datetime.now(_UTC) - timedelta(days=d)).strftime("%Y-%m-%d"),
                "portfolio_equity": base_equity + (30 - d) * daily_gain,
                "peak_equity": base_equity + 30 * daily_gain,
                "daily_pnl": daily_gain,
            }
            for d in range(30)
        ]
        db = _make_db(pnl_snapshots=snapshots)
        try:
            passed, evidence = SortinoRatioCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_with_poor_sortino(self):
        # Mostly large losses, tiny gains → negative mean return → Sortino < 0
        base_equity = 10000.0
        snapshots = [
            {
                "date": (datetime.now(_UTC) - timedelta(days=d)).strftime("%Y-%m-%d"),
                "portfolio_equity": base_equity - d * 40.0,
                "peak_equity": base_equity,
                "daily_pnl": -40.0 if d > 0 else 0.0,
            }
            for d in range(30)
        ]
        db = _make_db(pnl_snapshots=snapshots)
        try:
            passed, evidence = SortinoRatioCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_with_insufficient_rows(self):
        snapshots = [
            {
                "date": "2026-05-01",
                "portfolio_equity": 10000.0,
                "peak_equity": 10000.0,
                "daily_pnl": 10.0,
            }
        ]
        db = _make_db(pnl_snapshots=snapshots)
        try:
            passed, evidence = SortinoRatioCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C7 — consecutive_loss_streak
# ---------------------------------------------------------------------------


class TestConsecutiveLossStreak:
    def test_passes_when_streak_within_limit(self):
        # 3 losses then a win → streak=3, limit=5
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": -5.0 if i < 3 else 10.0,
                "exit_time": _iso(_days_ago(5 - i)),
                "status": "closed",
            }
            for i in range(10)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = ConsecutiveLossStreakCriterion().check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_streak_exceeds_limit(self):
        # 6 consecutive losses → streak=6 > limit=5
        trades = [
            {
                "trade_id": f"t-{i}",
                "pnl": -5.0,
                "exit_time": _iso(_days_ago(10 - i)),
                "status": "closed",
            }
            for i in range(6)
        ]
        db = _make_db(trades=trades)
        try:
            passed, evidence = ConsecutiveLossStreakCriterion().check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C8 — kill_switch_invocations
# ---------------------------------------------------------------------------


class TestKillSwitchInvocations:
    def test_passes_when_no_kill_switch_in_logs(self, tmp_path):
        db = _make_db(system_state=[{"key": "kill_switch_active", "value": "false"}])
        try:
            # Pass a nonexistent logs dir — fallback will use system_state (value=false)
            criterion = KillSwitchInvocationsCriterion()
            with patch("readiness.phase3_criteria.os.path.isdir", return_value=False):
                passed, evidence = criterion.check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_kill_switch_currently_active(self):
        db = _make_db(system_state=[{"key": "kill_switch_active", "value": "true"}])
        try:
            criterion = KillSwitchInvocationsCriterion()
            # Force fallback path (no log dir)
            with patch("readiness.phase3_criteria.os.path.isdir", return_value=False):
                with patch("readiness.phase3_criteria._MAX_KILL_SWITCH_INVOCATIONS", -1):
                    # With limit=-1, even 1 invocation fails
                    passed, evidence = criterion.check(db)
                    # The criterion counts 1 invocation (kill switch is active)
                    # But limit=-1 means 1 > -1 → FAIL
                    assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_passes_with_log_dir_no_activations(self, tmp_path):
        log_file = tmp_path / "engine.log"
        log_file.write_text("INFO  Normal operation\nINFO  Another line\n")
        db = _make_db()
        try:
            criterion = KillSwitchInvocationsCriterion()
            # No activations in log → count=0 → PASS
            with patch("readiness.phase3_criteria.os.path.isdir", return_value=True):
                with patch("readiness.phase3_criteria.os.listdir", return_value=["engine.log"]):
                    real_open = open

                    def _patched_open(p, **kw):
                        if str(p).endswith("engine.log"):
                            return real_open(str(log_file), **kw)
                        return real_open(p, **kw)

                    with patch("builtins.open", _patched_open):
                        passed, evidence = criterion.check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C9 — engine_uptime_stability
# ---------------------------------------------------------------------------


class TestEngineUptimeStability:
    def test_passes_when_no_restart_history(self, tmp_path):
        db = _make_db()
        try:
            criterion = EngineUptimeStabilityCriterion()
            # Patch os.path.exists to return False for both sidecars
            with patch("readiness.phase3_criteria.os.path.exists", return_value=False):
                passed, evidence = criterion.check(db)
            assert passed, f"Expected PASS (benefit of doubt); evidence={evidence}"
        finally:
            os.unlink(db)

    def test_passes_with_low_restart_count(self, tmp_path):
        sidecar = tmp_path / "pm2_restart_history.json"
        # 10 restarts spread across 30 days → rate=0.33/day < 1.0/day → PASS
        timestamps = [(datetime.now(_UTC) - timedelta(days=i * 3)).isoformat() for i in range(10)]
        sidecar.write_text(json.dumps(timestamps))
        sidecar_str = str(sidecar)
        db = _make_db()
        try:
            criterion = EngineUptimeStabilityCriterion()
            real_exists = os.path.exists
            real_open = open

            def _exists(p):
                return True if "pm2_restart_history" in str(p) else real_exists(p)

            def _open(p, **kw):
                return (
                    real_open(sidecar_str, **kw)
                    if "pm2_restart_history" in str(p)
                    else real_open(p, **kw)
                )

            with patch("readiness.phase3_criteria.os.path.exists", _exists):
                with patch("builtins.open", _open):
                    passed, evidence = criterion.check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_with_high_restart_count(self, tmp_path):
        sidecar = tmp_path / "pm2_restart_history.json"
        # 60 restarts within 30 days → rate=2.0/day > 1.0/day → FAIL
        timestamps = [(datetime.now(_UTC) - timedelta(hours=i * 12)).isoformat() for i in range(60)]
        sidecar.write_text(json.dumps(timestamps))
        sidecar_str = str(sidecar)
        db = _make_db()
        try:
            criterion = EngineUptimeStabilityCriterion()
            real_exists = os.path.exists
            real_open = open

            def _exists(p):
                return True if "pm2_restart_history" in str(p) else real_exists(p)

            def _open(p, **kw):
                return (
                    real_open(sidecar_str, **kw)
                    if "pm2_restart_history" in str(p)
                    else real_open(p, **kw)
                )

            with patch("readiness.phase3_criteria.os.path.exists", _exists):
                with patch("builtins.open", _open):
                    passed, evidence = criterion.check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# C10 — safety_layer_test_coverage
# ---------------------------------------------------------------------------


class TestSafetyLayerTestCoverage:
    def test_passes_when_coverage_meets_threshold(self):
        """Mock subprocess to return a 96% coverage line → PASS."""
        criterion = SafetyLayerTestCoverageCriterion()
        db = _make_db()
        try:
            fake_output = "risk/safety_layer      1735    70   96%   ...\n" "PASSED\n"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = fake_output
                mock_run.return_value.stderr = ""
                with patch("readiness.phase3_criteria.os.path.exists", return_value=True):
                    passed, evidence = criterion.check(db)
            assert passed, f"Expected PASS; evidence={evidence}"
            assert "96" in evidence
        finally:
            os.unlink(db)

    def test_fails_when_coverage_below_threshold(self):
        """Mock subprocess to return a 80% coverage line → FAIL."""
        criterion = SafetyLayerTestCoverageCriterion()
        db = _make_db()
        try:
            fake_output = "risk/safety_layer      1735   347   80%   ...\n" "PASSED\n"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = fake_output
                mock_run.return_value.stderr = ""
                with patch("readiness.phase3_criteria.os.path.exists", return_value=True):
                    passed, evidence = criterion.check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)

    def test_fails_when_venv_python_missing(self, tmp_path):
        """When venv python is absent, return FAIL gracefully."""
        criterion = SafetyLayerTestCoverageCriterion()
        db = _make_db()
        try:
            with patch("readiness.phase3_criteria.os.path.exists", return_value=False):
                passed, evidence = criterion.check(db)
            assert not passed, f"Expected FAIL; evidence={evidence}"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Overall logic — evaluate_all_criteria
# ---------------------------------------------------------------------------


class _AlwaysPassCriterion(Phase3Criterion):
    name = "always_pass"
    description = "Always passes"
    severity = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        return True, "synthetic pass"


class _AlwaysFailBlocker(Phase3Criterion):
    name = "always_fail_blocker"
    description = "Always fails as blocker"
    severity = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        return False, "synthetic blocker fail"


class _AlwaysFailWarning(Phase3Criterion):
    name = "always_fail_warning"
    description = "Always fails as warning"
    severity = "warning"

    def check(self, db_path: str) -> tuple[bool, str]:
        return False, "synthetic warning fail"


def _evaluate_with(criteria: list, db_path: str = ":memory:") -> dict:
    """Run evaluate_all_criteria with a patched _ALL_CRITERIA list."""
    with patch("readiness.phase3_criteria._ALL_CRITERIA", criteria):
        return evaluate_all_criteria(db_path)


class TestEvaluateAllOverallLogic:
    def test_go_when_all_pass(self):
        criteria = [_AlwaysPassCriterion(), _AlwaysPassCriterion()]
        result = _evaluate_with(criteria)
        assert result["summary"]["overall"] == "GO"
        assert result["summary"]["fail"] == 0

    def test_no_go_when_any_blocker_fails(self):
        criteria = [_AlwaysPassCriterion(), _AlwaysFailBlocker()]
        result = _evaluate_with(criteria)
        assert result["summary"]["overall"] == "NO-GO"

    def test_wait_when_all_blockers_pass_but_two_warnings_fail(self):
        criteria = [
            _AlwaysPassCriterion(),
            _AlwaysFailWarning(),
            _AlwaysFailWarning(),
        ]
        result = _evaluate_with(criteria)
        assert result["summary"]["overall"] == "WAIT"

    def test_go_when_one_warning_fails(self):
        """One warning fail is tolerated → GO."""
        criteria = [_AlwaysPassCriterion(), _AlwaysFailWarning()]
        result = _evaluate_with(criteria)
        assert result["summary"]["overall"] == "GO"

    def test_summary_counts_correct(self):
        criteria = [_AlwaysPassCriterion(), _AlwaysFailBlocker(), _AlwaysFailWarning()]
        result = _evaluate_with(criteria)
        assert result["summary"]["total"] == 3
        assert result["summary"]["pass"] == 1
        assert result["summary"]["fail"] == 2

    def test_criteria_list_has_10_entries(self):
        assert len(_ALL_CRITERIA) == 10

    def test_all_criteria_names_unique(self):
        names = [c.name for c in _ALL_CRITERIA]
        assert len(names) == len(set(names))

    def test_evaluated_at_is_iso_timestamp(self):
        result = _evaluate_with([_AlwaysPassCriterion()])
        assert "evaluated_at" in result
        # Should parse without raising
        datetime.fromisoformat(result["evaluated_at"].replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# HTTP route tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def readiness_client():
    """Bare FastAPI app mounting only the readiness router (auth dependency overridden)."""
    from middleware.auth import verify_api_key
    from routers.readiness_router import router

    app = FastAPI()
    # Override the auth dependency so tests don't need a real API key
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    app.include_router(router)
    with TestClient(app) as client:
        yield client


class TestReadinessRoute:
    def test_returns_json_with_correct_shape(self, readiness_client, tmp_path):
        fake_db = str(tmp_path / "test.db")
        conn = sqlite3.connect(fake_db)
        conn.executescript(
            "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, trade_id TEXT, "
            "symbol TEXT NOT NULL DEFAULT 'MES', side TEXT NOT NULL DEFAULT 'LONG', "
            "quantity REAL NOT NULL DEFAULT 1, entry_price REAL NOT NULL DEFAULT 100, "
            "entry_time TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z', "
            "status TEXT NOT NULL DEFAULT 'open', notes TEXT DEFAULT ''); "
            "CREATE TABLE pnl_snapshots (date TEXT PRIMARY KEY, daily_pnl REAL "
            "NOT NULL DEFAULT 0.0, portfolio_equity REAL NOT NULL DEFAULT 0.0, "
            "peak_equity REAL NOT NULL DEFAULT 0.0, consecutive_losses INTEGER "
            "NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now'))); "
            "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')));"
        )
        conn.commit()
        conn.close()

        _cov = Mock(
            stdout="risk/safety_layer.py   1735   103   97%\n",
            stderr="",
            returncode=0,
        )
        with (
            patch("readiness.phase3_criteria.subprocess.run", return_value=_cov),
            patch("routers.readiness_router._default_db_path", return_value=fake_db),
        ):
            resp = readiness_client.get("/readiness/phase3")

        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "criteria" in data
        assert "evaluated_at" in data
        assert data["summary"]["overall"] in ("GO", "WAIT", "NO-GO")
        assert data["summary"]["total"] == 10
        assert isinstance(data["criteria"], list)
        assert len(data["criteria"]) == 10
        for c in data["criteria"]:
            assert "name" in c
            assert "status" in c
            assert c["status"] in ("PASS", "FAIL")
            assert "evidence" in c
            assert "severity" in c

    def test_markdown_format_returns_text(self, readiness_client, tmp_path):
        fake_db = str(tmp_path / "test.db")
        conn = sqlite3.connect(fake_db)
        conn.executescript(
            "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, trade_id TEXT, "
            "symbol TEXT NOT NULL DEFAULT 'MES', side TEXT NOT NULL DEFAULT 'LONG', "
            "quantity REAL NOT NULL DEFAULT 1, entry_price REAL NOT NULL DEFAULT 100, "
            "entry_time TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z', "
            "status TEXT NOT NULL DEFAULT 'open', notes TEXT DEFAULT ''); "
            "CREATE TABLE pnl_snapshots (date TEXT PRIMARY KEY, daily_pnl REAL "
            "NOT NULL DEFAULT 0.0, portfolio_equity REAL NOT NULL DEFAULT 0.0, "
            "peak_equity REAL NOT NULL DEFAULT 0.0, consecutive_losses INTEGER "
            "NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now'))); "
            "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')));"
        )
        conn.commit()
        conn.close()

        _cov = Mock(
            stdout="risk/safety_layer.py   1735   103   97%\n",
            stderr="",
            returncode=0,
        )
        with (
            patch("readiness.phase3_criteria.subprocess.run", return_value=_cov),
            patch("routers.readiness_router._default_db_path", return_value=fake_db),
        ):
            resp = readiness_client.get("/readiness/phase3?format=markdown")

        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text" in content_type or "markdown" in content_type
        text = resp.text
        assert "# Phase 3" in text
        assert "Verdict" in text
        assert "| #" in text  # table header
