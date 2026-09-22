"""Tests for live_readiness — Phase 1 deployment-gate.

Validates each of the 7 mission-accomplished checks in isolation, plus
the aggregated pass/fail logic that determines exit code.
"""

from __future__ import annotations

import json
import sqlite3
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


def _make_paper_trades_db(path: Path) -> None:
    """Create an empty paper_trades table mirroring the engine schema columns
    that live_readiness reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                entry_price REAL,
                exit_price REAL,
                entry_time TEXT,
                exit_time TEXT,
                pnl REAL,
                status TEXT,
                notes TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Isolate live_readiness.VERDICTS_DIR + PAPER_TRADES_DB_PATH to tmp dirs.

    By default the paper-trades store points at a non-existent DB path so tests
    exercise the verdict-date-proxy fallback. Tests that need real paper-trade
    data should write via the `paper_trades_path` fixture.
    """
    monkeypatch.setattr(lr, "VERDICTS_DIR", tmp_path)
    monkeypatch.setattr(lr, "PAPER_TRADES_DB_PATH", tmp_path / "jarvis_trader.db")
    return tmp_path


@pytest.fixture
def paper_trades_path(tmp_path, monkeypatch):
    """Isolate live_readiness.PAPER_TRADES_DB_PATH to a fresh temp SQLite DB so
    tests can write curated paper_trades rows. Returns the DB Path."""
    p = tmp_path / "jarvis_trader.db"
    _make_paper_trades_db(p)
    monkeypatch.setattr(lr, "PAPER_TRADES_DB_PATH", p)
    monkeypatch.setattr(lr, "VERDICTS_DIR", tmp_path / "verdicts")
    return p


def _write_trade(
    path: Path,
    *,
    symbol: str,
    is_open: bool = False,
    entry_age_days: float = 1.0,
    pnl: float | None = 0.0,
    status: str | None = None,
) -> None:
    """Insert one paper_trades row into the curated SQLite store.

    status defaults to 'open' when is_open else 'closed'. Pass an explicit
    status (e.g. 'phantom', 'cancelled_duplicate') to exercise the
    curated-out-exclusion path.
    """
    if status is None:
        status = "open" if is_open else "closed"
    entry_dt = datetime.now(tz=timezone.utc) - timedelta(days=entry_age_days)
    if not path.exists():
        _make_paper_trades_db(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO paper_trades (trade_id, symbol, side, quantity, "
            "entry_price, exit_price, entry_time, exit_time, pnl, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"test-{symbol}-{entry_age_days}-{status}",
                symbol,
                "buy",
                1.0,
                5800.0,
                None if is_open else 5810.0,
                entry_dt.isoformat(),
                None if is_open else (entry_dt + timedelta(hours=2)).isoformat(),
                None if is_open else pnl,
                status,
                "test",
            ),
        )
        conn.commit()
    finally:
        conn.close()


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


def test_c1_fail_when_no_verdict_and_no_trades(tmp_verdicts_dir):
    """No verdict and no paper trades → can't authorize."""
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "missing" in result.detail.lower() or "no paper trades" in result.detail.lower()


def test_c1_falls_back_to_verdict_proxy_when_no_trades(tmp_verdicts_dir):
    """Verdict exists but no paper trades yet → use verdict-creation-date as proxy.

    This is the bootstrap state right after a refresh — verdict landed but
    paper trades haven't fired yet. Should report FAIL with informative detail
    about the IB Gateway / engine routing requirement.
    """
    _write_verdict(
        tmp_verdicts_dir, symbol="MES", family="trend", rank=11, verdict="PASS", age_days=5.0
    )
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    # New behavior: even a 31+ day-old verdict won't pass without real trades
    assert "no mes paper trades" in result.detail.lower()


def test_c1_fail_when_too_few_closed_trades(paper_trades_path):
    """Real paper trades exist but n_closed < 30 → still FAIL."""
    for i in range(5):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=20 - i, pnl=10.0)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "closed_trades=5" in result.detail


def test_c1_fail_when_days_under_30(paper_trades_path):
    """30+ closed trades but first entry < 30 days ago → FAIL on days criterion."""
    for _ in range(35):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=10, pnl=5.0)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "days=10" in result.detail


def test_c1_fail_when_forward_pf_below_threshold(paper_trades_path):
    """Days + count OK but forward_pf < 1.0 → FAIL on edge criterion."""
    # First trade 31 days ago, then 30 closed losers
    _write_trade(paper_trades_path, symbol="MES", entry_age_days=31, pnl=-10.0)
    for _ in range(29):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=20, pnl=-10.0)
    # Plus one tiny winner so forward_pf is computable but < 1.0
    _write_trade(paper_trades_path, symbol="MES", entry_age_days=15, pnl=5.0)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "forward_pf" in result.detail.lower()


def test_c1_pass_when_all_thresholds_met(paper_trades_path):
    """31 days elapsed + 30 closed + forward_pf > 1.0 → PASS."""
    # First trade 31 days ago, mix of 20 winners + 10 losers
    _write_trade(paper_trades_path, symbol="MES", entry_age_days=31, pnl=20.0)
    for _ in range(19):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=20, pnl=15.0)
    for _ in range(10):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=15, pnl=-5.0)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is True
    assert "PASS" in result.detail


def test_c1_only_counts_closed_trades(paper_trades_path):
    """Open trades shouldn't satisfy the count threshold."""
    # 35 open trades but 0 closed → fails on n_closed
    for _ in range(35):
        _write_trade(paper_trades_path, symbol="MES", is_open=True, entry_age_days=31)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "closed_trades=0" in result.detail


def test_c1_filters_by_symbol(paper_trades_path):
    """Trades for other symbols shouldn't count toward MES validation.

    Writes a MES verdict so we exercise the "no MES trades + verdict-proxy"
    branch, then writes 35 MGC trades. Expected: FAIL because zero MES trades
    counted toward the threshold (MGC trades are filtered out).
    """
    verdicts_dir = paper_trades_path.parent / "verdicts"
    _write_verdict(
        verdicts_dir,
        symbol="MES",
        family="trend",
        rank=11,
        verdict="PASS",
        age_days=5.0,
    )
    for _ in range(35):
        _write_trade(paper_trades_path, symbol="MGC", entry_age_days=31, pnl=10.0)
    result = lr.check_c1_mes_paper_validation()
    assert result.passed is False
    assert "no mes paper trades" in result.detail.lower()


def test_query_stats_excludes_curated_out_statuses(paper_trades_path):
    """Regression (2026-06-16): the forward-test reads the curated paper_trades
    DB, so voided/duplicate/contaminated rows must NOT count as live.

    Reproduces the bug where the raw jsonl reader reported a phantom MES
    "+$30,918 / 43 open" book: rows the live engine had cancelled/voided still
    showed as open. Here genuine rows count; phantom/cancelled rows are dropped.
    """
    # 3 genuine closed winners + 1 genuine open
    for _ in range(3):
        _write_trade(paper_trades_path, symbol="MES", entry_age_days=10, pnl=100.0)
    _write_trade(paper_trades_path, symbol="MES", is_open=True, entry_age_days=5)
    # Curated-out noise that must be excluded
    _write_trade(paper_trades_path, symbol="MES", entry_age_days=8, pnl=9999.0, status="phantom")
    _write_trade(
        paper_trades_path, symbol="MES", is_open=True, entry_age_days=7, status="cancelled_duplicate"
    )
    _write_trade(
        paper_trades_path,
        symbol="MES",
        is_open=True,
        entry_age_days=6,
        status="cancelled_contaminated",
    )

    stats = lr._query_paper_trade_stats("MES")
    assert stats["available"] is True
    assert stats["n_closed"] == 3  # phantom closer excluded
    assert stats["n_open"] == 1  # both cancelled opens excluded
    assert stats["total_pnl"] == pytest.approx(300.0)  # 9999 phantom not summed


def test_query_stats_available_false_when_db_missing(tmp_verdicts_dir):
    """No curated DB on disk → available False (drives the verdict-proxy fallback)."""
    stats = lr._query_paper_trade_stats("MES")
    assert stats["available"] is False
    assert stats["n_closed"] == 0
    assert stats["n_open"] == 0


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


def test_c2_fail_when_mgc_pass_is_blocked_and_disabled(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MGC", family="trend", rank=4, verdict="PASS")
    result = lr.check_c2_second_symbol()
    assert result.passed is False
    assert "blocked_or_disabled=['MGC']" in result.detail


def test_c2_pass_when_non_mes_pass_is_actionable(tmp_verdicts_dir, monkeypatch):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="FOO", family="trend", rank=4, verdict="PASS")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    monkeypatch.setattr(
        "backtest.paper_config.PAPER_CONFIGS",
        {"FOO": {"enabled": True, "strategy": "sma_trend"}},
    )
    result = lr.check_c2_second_symbol()
    assert result.passed is True
    assert "FOO" in result.detail


def test_c2_pass_when_options_watchlist_symbol_has_pass_without_paper_config(
    tmp_verdicts_dir, monkeypatch
):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="QQQ", family="trend", rank=0, verdict="PASS")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    monkeypatch.setattr("backtest.paper_config.PAPER_CONFIGS", {})
    monkeypatch.setattr(lr, "_load_options_watchlist", lambda: {"SPY", "QQQ"})

    result = lr.check_c2_second_symbol()

    assert result.passed is True
    assert "QQQ" in result.detail


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


def test_c3_handles_findings_array_format(monkeypatch, tmp_path):
    """scan-credentials.ps1 native output is a list of finding dicts."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    findings = [
        {"severity": "HIGH", "type": "ForbiddenPath", "path": "/foo/.env"},
        {"severity": "HIGH", "type": "Pattern:Anthropic", "path": "/bar/x"},
        {"severity": "MEDIUM", "type": "PlaintextPassword", "path": "/baz/y"},
    ]
    (log_dir / "scan-credentials-latest.json").write_text(json.dumps(findings))
    result = lr.check_c3_phase0_complete()
    assert result.passed is False
    assert "2" in result.detail  # 2 HIGH findings


def test_c3_pass_with_findings_array_no_high(monkeypatch, tmp_path):
    """Findings array with only MEDIUM severity → PASS."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    findings = [
        {"severity": "MEDIUM", "type": "PlaintextPassword", "path": "/foo/bar"},
    ]
    (log_dir / "scan-credentials-latest.json").write_text(json.dumps(findings))
    result = lr.check_c3_phase0_complete()
    assert result.passed is True


def test_c3_handles_dict_with_findings_subkey(monkeypatch, tmp_path):
    """Some scanner formats nest findings under a 'findings' key."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    payload = {
        "scanned_at": "2026-05-06",
        "findings": [
            {"severity": "HIGH", "type": "X"},
            {"severity": "HIGH", "type": "Y"},
            {"severity": "HIGH", "type": "Z"},
        ],
    }
    (log_dir / "scan-credentials-latest.json").write_text(json.dumps(payload))
    result = lr.check_c3_phase0_complete()
    assert result.passed is False
    assert "3" in result.detail


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


def test_c7_pass_when_pass_symbol_is_blocked_but_paper_disabled(
    tmp_verdicts_dir, monkeypatch
):
    """MGC's stale PASS does not require unblocking while paper_config is disabled."""
    _write_verdict(tmp_verdicts_dir, symbol="MGC", family="trend", rank=4, verdict="PASS")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset({"MGC"}))
    monkeypatch.setattr(
        "backtest.paper_config.PAPER_CONFIGS",
        {"MGC": {"enabled": False, "strategy": "sma_trend"}},
    )
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is True


def test_c7_fail_when_fail_only_symbol_not_blocked(tmp_verdicts_dir, monkeypatch):
    """A FAIL-only symbol should be in DO_NOT_TRADE_SYMBOLS — this was the M2K bug."""
    _write_verdict(tmp_verdicts_dir, symbol="M2K", verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    monkeypatch.setattr(
        "backtest.paper_config.PAPER_CONFIGS",
        {"M2K": {"enabled": False, "strategy": "sma_trend"}},
    )
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is False
    assert "M2K" in result.detail


def test_c7_mes_fail_only_symbol_allowed_unblocked_by_standing_directive(
    tmp_verdicts_dir, monkeypatch
):
    """MES is the explicit exception: FAIL-only verdicts must not disable it."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is True


def test_c7_mixed_pass_and_fail_symbol_allowed_if_any_pass(tmp_verdicts_dir, monkeypatch):
    """If a symbol has any PASS verdict, having a sibling FAIL doesn't require blocking."""
    _write_verdict(tmp_verdicts_dir, symbol="MES", family="trend", rank=11, verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MES", family="orb", rank=1, verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    result = lr.check_c7_do_not_trade_symbols()
    assert result.passed is True


def test_c7_ignores_options_underlying_not_in_futures_policy_scope(
    tmp_verdicts_dir, monkeypatch
):
    """SPY verdicts are not governed by the futures DO_NOT_TRADE_SYMBOLS set."""
    _write_verdict(tmp_verdicts_dir, symbol="SPY", family="trend", rank=1, verdict="FAIL")
    monkeypatch.setattr("backtest.signals.DO_NOT_TRADE_SYMBOLS", frozenset())
    monkeypatch.setattr("backtest.paper_config.PAPER_CONFIGS", {})
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
