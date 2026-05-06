"""Tests for live_readiness — Phase 1 deployment-gate.

Validates each of the 7 mission-accomplished checks in isolation, plus
the aggregated pass/fail logic that determines exit code.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest import live_readiness as lr

# ---------------------------------------------------------- #
# Helpers                                                    #
# ---------------------------------------------------------- #


def _write_verdict(
    dir_: Path,
    *,
    symbol: str,
    family: str = "trend",
    rank: int = 11,
    verdict: str = "PASS",
    age_days: float = 1.0,
) -> Path:
    """Minimal verdict JSON sufficient for live_readiness checks."""
    dir_.mkdir(parents=True, exist_ok=True)
    created = (datetime.now(tz=timezone.utc) - timedelta(days=age_days)).isoformat()
    doc = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "created_at": created,
    }
    if symbol == "MES" and family == "trend" and rank == 11:
        path = dir_ / "MES_trend_rank11.json"
    else:
        path = dir_ / f"{symbol}_{family}_rank{rank}.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Isolate live_readiness.VERDICTS_DIR to a tmp dir."""
    monkeypatch.setattr(lr, "VERDICTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def healthy_engine(monkeypatch):
    """Stub _fetch_engine_health to return a fully-healthy response."""

    def _fake():
        return {
            "status": "ok",
            "tradingview_mcp_healthy": True,
            "tv_mcp_status": "healthy",
            "llm_path_healthy": True,
            "kill_switch_active": False,
            "uptime_seconds": 3600,
        }

    monkeypatch.setattr(lr, "_fetch_engine_health", _fake)


@pytest.fixture
def offline_engine(monkeypatch):
    """Stub _fetch_engine_health to return None (engine unreachable)."""
    monkeypatch.setattr(lr, "_fetch_engine_health", lambda: None)


# ---------------------------------------------------------- #
# C1 — MES paper validation                                  #
# ---------------------------------------------------------- #


def test_c1_fail_when_mes_verdict_missing(tmp_verdicts_dir):
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "verdict not found" in result.detail.lower() or "in progress" in result.detail.lower()


def test_c1_fail_when_paper_clock_under_30_days(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir, symbol="MES", family="trend", rank=11, verdict="PASS", age_days=5.0
    )
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "day" in result.detail.lower()


def test_c1_pass_when_paper_clock_complete(tmp_verdicts_dir):
    """MES verdict 31+ days old means paper-trade clock has matured."""
    _write_verdict(
        tmp_verdicts_dir, symbol="MES", family="trend", rank=11, verdict="PASS", age_days=31.0
    )
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is True


# ---------------------------------------------------------- #
# C2 — Second symbol validated                               #
# ---------------------------------------------------------- #


def test_c2_fail_with_no_pass_verdicts(tmp_verdicts_dir):
    result = lr.check_c2_second_symbol()
    assert result.passed is False
    assert result.fix is not None


def test_c2_fail_with_only_mes_pass(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    result = lr.check_c2_second_symbol()
    assert result.passed is False
    assert "MES" in result.detail


def test_c2_pass_when_mgc_also_passes(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MGC", family="trend", rank=4, verdict="PASS")
    result = lr.check_c2_second_symbol()
    assert result.passed is True
    assert "MGC" in result.detail


def test_c2_ignores_fail_verdicts(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="M2K", verdict="FAIL")
    result = lr.check_c2_second_symbol()
    assert result.passed is False  # M2K FAIL doesn't count as second symbol


# ---------------------------------------------------------- #
# C3 — Phase 0 credential rotation                           #
# ---------------------------------------------------------- #


def test_c3_advisory_when_scan_log_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = lr.check_c3_phase0_complete()
    assert result.blocking is False  # advisory only when log missing
    assert result.passed is False


def test_c3_pass_when_zero_high_findings(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "scan-credentials-latest.json").write_text(json.dumps({"n_high": 0}))
    result = lr.check_c3_phase0_complete()
    assert result.passed is True


def test_c3_fail_when_high_findings_remain(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "scan-credentials-latest.json").write_text(json.dumps({"n_high": 12}))
    result = lr.check_c3_phase0_complete()
    assert result.passed is False
    assert "12" in result.detail


# ---------------------------------------------------------- #
# C4 — Engine health                                         #
# ---------------------------------------------------------- #


def test_c4_fail_when_engine_unreachable(offline_engine):
    result = lr.check_c4_engine_health()
    assert result.passed is False
    assert "unreachable" in result.detail.lower()


def test_c4_pass_when_all_healthy(healthy_engine):
    result = lr.check_c4_engine_health()
    assert result.passed is True
    assert "status=ok" in result.detail


def test_c4_fail_when_status_not_ok(monkeypatch):
    monkeypatch.setattr(
        lr,
        "_fetch_engine_health",
        lambda: {
            "status": "degraded",
            "tv_mcp_status": "healthy",
            "llm_path_healthy": True,
            "kill_switch_active": False,
        },
    )
    result = lr.check_c4_engine_health()
    assert result.passed is False
    assert "status=degraded" in result.detail


def test_c4_fail_when_llm_path_unhealthy(monkeypatch):
    monkeypatch.setattr(
        lr,
        "_fetch_engine_health",
        lambda: {
            "status": "ok",
            "tv_mcp_status": "healthy",
            "llm_path_healthy": False,
            "kill_switch_active": False,
        },
    )
    result = lr.check_c4_engine_health()
    assert result.passed is False
    assert "llm_path" in result.detail


# ---------------------------------------------------------- #
# C5 — Kill switch INACTIVE                                  #
# ---------------------------------------------------------- #


def test_c5_pass_when_kill_switch_inactive(healthy_engine):
    result = lr.check_c5_kill_switch_inactive()
    assert result.passed is True


def test_c5_fail_when_kill_switch_active(monkeypatch):
    monkeypatch.setattr(
        lr, "_fetch_engine_health", lambda: {"status": "ok", "kill_switch_active": True}
    )
    result = lr.check_c5_kill_switch_inactive()
    assert result.passed is False
    assert "halted" in result.detail.lower()


def test_c5_fails_safe_when_engine_unreachable(offline_engine):
    """Defaults to FAIL (safe) when we can't verify state."""
    result = lr.check_c5_kill_switch_inactive()
    assert result.passed is False


# ---------------------------------------------------------- #
# C6 — All verdicts current                                  #
# ---------------------------------------------------------- #


def test_c6_fail_with_no_pass_verdicts(tmp_verdicts_dir):
    result = lr.check_c6_verdicts_current()
    assert result.passed is False


def test_c6_pass_with_recent_verdict(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS", age_days=5.0)
    result = lr.check_c6_verdicts_current()
    assert result.passed is True


def test_c6_fail_with_expired_verdict(tmp_verdicts_dir):
    """Verdict older than VERDICT_TTL_DAYS counts as expired."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS", age_days=lr.VERDICT_TTL_DAYS + 5)
    result = lr.check_c6_verdicts_current()
    assert result.passed is False
    assert "expired" in result.detail.lower()


def test_c6_warns_about_expiring_soon(tmp_verdicts_dir):
    """Within 7 days of expiry → still PASS but warning shown."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS", age_days=lr.VERDICT_TTL_DAYS - 3)
    result = lr.check_c6_verdicts_current()
    assert result.passed is True
    assert "expiring" in result.detail.lower()


# ---------------------------------------------------------- #
# C7 — DO_NOT_TRADE_SYMBOLS sync                             #
# ---------------------------------------------------------- #


def test_c7_pass_when_consistent(tmp_verdicts_dir, monkeypatch):
    """PASS symbols not in blocklist; FAIL-only symbols are in blocklist."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MNQ", verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset({"MNQ"}))
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is True


def test_c7_fail_when_pass_symbol_blocked(tmp_verdicts_dir, monkeypatch):
    """A PASS verdict shouldn't be in DO_NOT_TRADE_SYMBOLS."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset({"MES"}))
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is False
    assert "MES" in result.detail


def test_c7_fail_when_fail_only_symbol_not_blocked(tmp_verdicts_dir, monkeypatch):
    """A FAIL-only symbol should be in DO_NOT_TRADE_SYMBOLS — this was the M2K bug."""
    _write_verdict(tmp_verdicts_dir, symbol="M2K", verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is False
    assert "M2K" in result.detail


def test_c7_pass_symbol_with_both_pass_and_fail_isnt_blocked(tmp_verdicts_dir, monkeypatch):
    """If a symbol has any PASS verdict, having a sibling FAIL doesn't require blocking."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", family="trend", rank=11, verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MES", family="orb", rank=1, verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is True


# ---------------------------------------------------------- #
# Aggregated run_all_checks                                  #
# ---------------------------------------------------------- #


def test_run_all_returns_seven_results(tmp_verdicts_dir, healthy_engine, monkeypatch):
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    results = lr.run_all_checks()
    assert len(results) == 7


def test_run_all_check_names_are_distinct(tmp_verdicts_dir, healthy_engine, monkeypatch):
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    results = lr.run_all_checks()
    names = [r.name for r in results]
    assert len(set(names)) == len(names)


def test_check_result_dataclass_serializes(tmp_verdicts_dir):
    """CheckResult must be JSON-serializable for --json mode."""
    from dataclasses import asdict

    r = lr.CheckResult(name="X", passed=True, detail="ok")
    d = asdict(r)
    assert json.loads(json.dumps(d))["name"] == "X"
