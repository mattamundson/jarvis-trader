"""
Tests for the OPT-IN readiness edge-mode decoupling in phase3_criteria.py.

The walk-forward edge proof (gate-v2 PASS on 2+ years OOS) + a small sample of
REAL execution fidelity can substitute for the paper-accrual edge gates
(100 trades / 60 days), which take ~15-30 years to accrue on a ~2-4 trade/year
SMA-trend strategy.

SAFETY INVARIANTS UNDER TEST:
- The default mode ("paper_accrual") is byte-identical to evaluate_all_criteria;
  _ALL_CRITERIA still has exactly 10 entries.
- The two new criteria declare severity "info" — they never block by default.
- "wfo_plus_fidelity" mode requires REAL fills (ALLOW_PAPER_SIMULATED_ORDERS=True)
  via ExecutionFidelity, so it yields NO-GO while that flag is False — inert until
  forward-test is enabled.
- This module never reads/writes LIVE_TRADING_ENABLED, never imports safety_layer,
  never mutates config (file-level invariant, unchanged).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest

from readiness import phase3_criteria as p3
from readiness.phase3_criteria import (
    _ALL_CRITERIA,
    EDGE_MODE_PAPER_ACCRUAL,
    EDGE_MODE_WFO_FIDELITY,
    VERDICT_TTL_DAYS,
    ExecutionFidelityCriterion,
    WalkForwardEdgeCriterion,
    _edge_mode,
    _effective_severity,
    _scan_current_pass_symbols,
    evaluate_all_criteria,
    evaluate_with_edge_mode,
)

# ---------------------------------------------------------------------------
# Temp-DB helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path, trades=None, health=None):
    """Build a minimal SQLite DB with paper_trades + health_snapshots."""
    db = tmp_path / "jarvis.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE paper_trades ("
        "id INTEGER PRIMARY KEY, symbol TEXT, status TEXT, pnl REAL, slippage_ticks REAL)"
    )
    conn.execute(
        "CREATE TABLE health_snapshots ("
        "ts_utc TEXT PRIMARY KEY, ibkr_data INTEGER, ibkr_exec INTEGER, kill_switch INTEGER)"
    )
    for t in trades or []:
        conn.execute(
            "INSERT INTO paper_trades (symbol, status, pnl, slippage_ticks) VALUES (?,?,?,?)",
            (t.get("symbol", "MES"), t.get("status", "closed"), t.get("pnl"), t.get("slippage_ticks")),
        )
    for h in health or []:
        conn.execute(
            "INSERT INTO health_snapshots (ts_utc, ibkr_data, ibkr_exec, kill_switch) VALUES (?,?,?,?)",
            (h["ts_utc"], h.get("ibkr_data"), h.get("ibkr_exec"), h.get("kill_switch")),
        )
    conn.commit()
    conn.close()
    return str(db)


def _write_verdict(dirpath, symbol, verdict, age_days=0):
    created = (p3._now_utc() - timedelta(days=age_days)).isoformat()
    (dirpath / f"{symbol}_trend.json").write_text(
        json.dumps({"symbol": symbol, "verdict": verdict, "created_at": created}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Invariants — default path untouched
# ---------------------------------------------------------------------------


def test_all_criteria_still_exactly_ten():
    """The standard registry is unchanged — default report is byte-identical."""
    assert len(_ALL_CRITERIA) == 10


def test_new_criteria_declare_info_severity():
    """New criteria never block by default (only promoted under wfo mode)."""
    assert WalkForwardEdgeCriterion().severity == "info"
    assert ExecutionFidelityCriterion().severity == "info"


def test_new_criteria_not_in_standard_registry():
    names = {c.name for c in _ALL_CRITERIA}
    assert "walk_forward_edge" not in names
    assert "execution_fidelity" not in names


# ---------------------------------------------------------------------------
# _edge_mode env parsing
# ---------------------------------------------------------------------------


def test_edge_mode_defaults_to_paper_accrual(monkeypatch):
    monkeypatch.delenv("READINESS_EDGE_MODE", raising=False)
    assert _edge_mode() == EDGE_MODE_PAPER_ACCRUAL


def test_edge_mode_reads_env(monkeypatch):
    monkeypatch.setenv("READINESS_EDGE_MODE", "wfo_plus_fidelity")
    assert _edge_mode() == EDGE_MODE_WFO_FIDELITY


def test_edge_mode_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("READINESS_EDGE_MODE", "live_now_please")
    assert _edge_mode() == EDGE_MODE_PAPER_ACCRUAL


# ---------------------------------------------------------------------------
# _effective_severity remapping
# ---------------------------------------------------------------------------


def test_effective_severity_paper_accrual_is_identity():
    for name in ("profit_factor", "walk_forward_edge", "kill_switch_invocations"):
        assert _effective_severity(name, "blocker", EDGE_MODE_PAPER_ACCRUAL) == "blocker"
        assert _effective_severity(name, "warning", EDGE_MODE_PAPER_ACCRUAL) == "warning"
        assert _effective_severity(name, "info", EDGE_MODE_PAPER_ACCRUAL) == "info"


def test_effective_severity_wfo_demotes_edge_accrual():
    for name in (
        "paper_trading_window",
        "paper_trades_count",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "sortino_ratio",
    ):
        assert _effective_severity(name, "blocker", EDGE_MODE_WFO_FIDELITY) == "info"


def test_effective_severity_wfo_promotes_substitutes():
    assert _effective_severity("walk_forward_edge", "info", EDGE_MODE_WFO_FIDELITY) == "blocker"
    assert _effective_severity("execution_fidelity", "info", EDGE_MODE_WFO_FIDELITY) == "blocker"


def test_effective_severity_wfo_keeps_operational():
    # Operational/safety criteria keep their declared severity in wfo mode.
    assert _effective_severity("kill_switch_invocations", "blocker", EDGE_MODE_WFO_FIDELITY) == "blocker"
    assert _effective_severity("consecutive_loss_streak", "warning", EDGE_MODE_WFO_FIDELITY) == "warning"


# ---------------------------------------------------------------------------
# _scan_current_pass_symbols
# ---------------------------------------------------------------------------


def test_scan_pass_symbols_fresh_pass_counts(tmp_path):
    _write_verdict(tmp_path, "MES", "PASS", age_days=1)
    _write_verdict(tmp_path, "MGC", "PASS", age_days=5)
    assert _scan_current_pass_symbols(str(tmp_path)) == {"MES", "MGC"}


def test_scan_pass_symbols_excludes_fail_and_stale(tmp_path):
    _write_verdict(tmp_path, "MES", "PASS", age_days=1)
    _write_verdict(tmp_path, "MNQ", "FAIL", age_days=1)
    _write_verdict(tmp_path, "MCL", "PASS", age_days=VERDICT_TTL_DAYS + 5)  # stale
    assert _scan_current_pass_symbols(str(tmp_path)) == {"MES"}


def test_scan_pass_symbols_missing_dir_empty(tmp_path):
    assert _scan_current_pass_symbols(str(tmp_path / "nope")) == set()


# ---------------------------------------------------------------------------
# WalkForwardEdgeCriterion
# ---------------------------------------------------------------------------


def test_wfe_no_pass_verdicts_fails(tmp_path, monkeypatch):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    monkeypatch.setattr(p3, "_verdicts_dir", lambda: str(vdir))
    db = _make_db(tmp_path)
    passed, _ = WalkForwardEdgeCriterion().check(db)
    assert passed is False


def test_wfe_no_trades_passes_with_pass_verdict(tmp_path, monkeypatch):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    _write_verdict(vdir, "MES", "PASS", age_days=1)
    monkeypatch.setattr(p3, "_verdicts_dir", lambda: str(vdir))
    db = _make_db(tmp_path)  # no closed trades
    passed, _ = WalkForwardEdgeCriterion().check(db)
    assert passed is True


def test_wfe_traded_symbol_with_verdict_passes(tmp_path, monkeypatch):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    _write_verdict(vdir, "MES", "PASS", age_days=1)
    monkeypatch.setattr(p3, "_verdicts_dir", lambda: str(vdir))
    db = _make_db(tmp_path, trades=[{"symbol": "MES", "status": "closed", "pnl": 10.0}])
    passed, _ = WalkForwardEdgeCriterion().check(db)
    assert passed is True


def test_wfe_traded_symbol_missing_verdict_fails(tmp_path, monkeypatch):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    _write_verdict(vdir, "MES", "PASS", age_days=1)
    monkeypatch.setattr(p3, "_verdicts_dir", lambda: str(vdir))
    # Trading MNQ but only MES has a verdict.
    db = _make_db(tmp_path, trades=[{"symbol": "MNQ", "status": "closed", "pnl": 10.0}])
    passed, evidence = WalkForwardEdgeCriterion().check(db)
    assert passed is False
    assert "MNQ" in evidence


# ---------------------------------------------------------------------------
# ExecutionFidelityCriterion
# ---------------------------------------------------------------------------


def _good_fill_db(tmp_path, n=15):
    trades = [
        {"symbol": "MES", "status": "closed", "pnl": (5.0 if i % 3 else -2.0), "slippage_ticks": 0.5}
        for i in range(n)
    ]
    # Health snapshot must be FRESH (<= HEALTH_SNAPSHOT_TTL_MIN) or Hardening 2
    # rejects it. Use "now" so the fidelity check exercises the real pass path.
    health = [
        {"ts_utc": p3._now_utc().isoformat(), "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}
    ]
    return _make_db(tmp_path, trades=trades, health=health)


def test_fidelity_inert_when_sim_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: False)
    db = _good_fill_db(tmp_path)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "ALLOW_PAPER_SIMULATED_ORDERS=False" in evidence


def test_fidelity_passes_with_real_fills(tmp_path, monkeypatch):
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    db = _good_fill_db(tmp_path, n=20)
    passed, _ = ExecutionFidelityCriterion().check(db)
    assert passed is True


def test_fidelity_insufficient_fills_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    db = _good_fill_db(tmp_path, n=5)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "5 real fills" in evidence


def test_fidelity_kill_switch_active_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    trades = [{"symbol": "MES", "status": "closed", "pnl": 5.0, "slippage_ticks": 0.5} for _ in range(20)]
    health = [
        {"ts_utc": p3._now_utc().isoformat(), "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 1}
    ]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "Kill switch" in evidence


def test_fidelity_losing_pf_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    # PF is checked before health, so the stale-but-irrelevant timestamp is fine:
    # this fails at the realized-PF floor regardless of the health snapshot.
    trades = [{"symbol": "MES", "status": "closed", "pnl": -5.0, "slippage_ticks": 0.5} for _ in range(20)]
    health = [{"ts_utc": "2026-06-01T19:00:00Z", "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "PF" in evidence


def test_fidelity_null_slippage_coverage_fails(tmp_path, monkeypatch):
    """Hardening 1: enough rows but NONE carry measured slippage -> FAIL.

    Closes the loophole where 15+ intent rows with NULL slippage_ticks passed
    while the slippage bound was silently skipped.
    """
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    trades = [
        {"symbol": "MES", "status": "closed", "pnl": 5.0, "slippage_ticks": None} for _ in range(20)
    ]
    health = [
        {"ts_utc": p3._now_utc().isoformat(), "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}
    ]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "measured slippage" in evidence


def test_fidelity_partial_slippage_coverage_fails(tmp_path, monkeypatch):
    """Hardening 1: 20 fills but only 10 with measured slippage -> still FAIL."""
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    trades = [
        {
            "symbol": "MES",
            "status": "closed",
            "pnl": 5.0,
            "slippage_ticks": (0.5 if i < 10 else None),
        }
        for i in range(20)
    ]
    health = [
        {"ts_utc": p3._now_utc().isoformat(), "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}
    ]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "10/20" in evidence


def test_fidelity_stale_health_fails(tmp_path, monkeypatch):
    """Hardening 2: a stale health snapshot cannot certify the broker is up now."""
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    trades = [{"symbol": "MES", "status": "closed", "pnl": 5.0, "slippage_ticks": 0.5} for _ in range(20)]
    stale_ts = (
        p3._now_utc() - timedelta(minutes=p3.HEALTH_SNAPSHOT_TTL_MIN + 30)
    ).isoformat()
    health = [{"ts_utc": stale_ts, "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "stale" in evidence.lower()


def test_fidelity_high_slippage_fails(tmp_path, monkeypatch):
    """Avg slippage above the tick bound fails even with full measured coverage."""
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: True)
    trades = [{"symbol": "MES", "status": "closed", "pnl": 5.0, "slippage_ticks": 3.0} for _ in range(20)]
    health = [
        {"ts_utc": p3._now_utc().isoformat(), "ibkr_data": 1, "ibkr_exec": 1, "kill_switch": 0}
    ]
    db = _make_db(tmp_path, trades=trades, health=health)
    passed, evidence = ExecutionFidelityCriterion().check(db)
    assert passed is False
    assert "slippage" in evidence.lower()


# ---------------------------------------------------------------------------
# evaluate_with_edge_mode — delegation + inertness + verdict logic
# ---------------------------------------------------------------------------


def test_default_mode_delegates_to_evaluate_all(tmp_path, monkeypatch):
    sentinel = {"summary": {"overall": "GO", "total": 10}, "criteria": [], "evaluated_at": "x"}
    monkeypatch.setattr(p3, "evaluate_all_criteria", lambda db: dict(sentinel))
    out = evaluate_with_edge_mode("anydb", mode=EDGE_MODE_PAPER_ACCRUAL)
    assert out["edge_mode"] == EDGE_MODE_PAPER_ACCRUAL
    assert out["summary"] == sentinel["summary"]


def test_wfo_mode_inert_while_sim_off(tmp_path, monkeypatch):
    """While ALLOW_PAPER_SIMULATED_ORDERS=False, wfo mode is NO-GO and edge gates are info."""
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    _write_verdict(vdir, "MES", "PASS", age_days=1)
    monkeypatch.setattr(p3, "_verdicts_dir", lambda: str(vdir))
    monkeypatch.setattr(p3, "_paper_sim_enabled", lambda: False)
    # Stub the safety-coverage criterion so the test doesn't shell out to pytest.
    monkeypatch.setattr(
        p3.SafetyLayerTestCoverageCriterion, "check", lambda self, db: (True, "stubbed")
    )
    db = _good_fill_db(tmp_path)  # fills exist, but sim is off
    report = evaluate_with_edge_mode(db, mode=EDGE_MODE_WFO_FIDELITY)

    assert report["edge_mode"] == EDGE_MODE_WFO_FIDELITY
    assert report["summary"]["overall"] == "NO-GO"
    by_name = {c["name"]: c for c in report["criteria"]}
    # execution_fidelity is a failing blocker (sim off)
    assert by_name["execution_fidelity"]["severity"] == "blocker"
    assert by_name["execution_fidelity"]["status"] == "FAIL"
    # edge-accrual gates demoted to info (non-blocking)
    assert by_name["profit_factor"]["severity"] == "info"
    assert by_name["paper_trades_count"]["severity"] == "info"
    # walk_forward_edge promoted to blocker
    assert by_name["walk_forward_edge"]["severity"] == "blocker"


class _Stub:
    def __init__(self, name, severity, passed):
        self.name = name
        self.description = "stub"
        self.severity = severity
        self._passed = passed

    def check(self, db_path):
        return self._passed, "stub-evidence"


def test_wfo_verdict_logic_go(monkeypatch):
    monkeypatch.setattr(
        p3,
        "_WFO_MODE_CRITERIA",
        [_Stub("b1", "blocker", True), _Stub("w1", "warning", True), _Stub("i1", "info", False)],
    )
    out = evaluate_with_edge_mode("unused", mode=EDGE_MODE_WFO_FIDELITY)
    assert out["summary"]["overall"] == "GO"


def test_wfo_verdict_logic_blocker_fail_is_nogo(monkeypatch):
    monkeypatch.setattr(
        p3,
        "_WFO_MODE_CRITERIA",
        [_Stub("b1", "blocker", False), _Stub("w1", "warning", True)],
    )
    out = evaluate_with_edge_mode("unused", mode=EDGE_MODE_WFO_FIDELITY)
    assert out["summary"]["overall"] == "NO-GO"


def test_wfo_verdict_logic_two_warnings_is_wait(monkeypatch):
    monkeypatch.setattr(
        p3,
        "_WFO_MODE_CRITERIA",
        [_Stub("b1", "blocker", True), _Stub("w1", "warning", False), _Stub("w2", "warning", False)],
    )
    out = evaluate_with_edge_mode("unused", mode=EDGE_MODE_WFO_FIDELITY)
    assert out["summary"]["overall"] == "WAIT"


def test_invalid_mode_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        p3.SafetyLayerTestCoverageCriterion, "check", lambda self, db: (True, "stubbed")
    )
    db = _make_db(tmp_path)
    out = evaluate_with_edge_mode(db, mode="live_now")
    assert out["edge_mode"] == EDGE_MODE_PAPER_ACCRUAL
