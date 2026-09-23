"""
Tests for backtest.roi_readiness (ROI trigger evaluator).

All tests are offline — no live engine, no real DB, no Discord.
Data is constructed in-memory via the module's internal functions.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add engine dir to path so imports work regardless of invocation directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.roi_readiness import (
    DAILY_PNL_TARGET,
    MAX_CONSEC_LOSS_DAYS,
    MAX_SINGLE_DAY_DD_PCT,
    STREAK_TARGET,
    VERDICT_TTL_DAYS,
    WIN_RATE_MIN,
    GateResult,
    ROIReadinessResult,
    _eval_g1_daily_pnl,
    _eval_g2_win_rate,
    _eval_g3_max_daily_drawdown,
    _eval_g4_consec_loss_days,
    _eval_g5_no_donottrade,
    _eval_g6_engine_uptime,
    _eval_g7_verdict_freshness,
    _trading_days_window,
    compute_consecutive_passing_days,
    evaluate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc
_TODAY = date(2026, 5, 7)  # fixed date for deterministic tests


def _make_snapshot(d: date, daily_pnl: float = 280.0, equity: float = 10_000.0) -> dict:
    return {
        "daily_pnl": daily_pnl,
        "portfolio_equity": equity,
        "peak_equity": equity,
        "consecutive_losses": 0 if daily_pnl >= 0 else 1,
    }


def _make_snapshots(
    days: list[date],
    daily_pnl: float = 280.0,
    equity: float = 10_000.0,
) -> dict[date, dict]:
    return {d: _make_snapshot(d, daily_pnl, equity) for d in days}


def _make_roundtrip(symbol: str = "MES", pnl: float = 50.0, exit_date: date = _TODAY) -> dict:
    return {"symbol": symbol, "pnl": pnl, "exit_date": exit_date}


def _make_14_day_window(as_of: date = _TODAY) -> list[date]:
    return _trading_days_window(as_of, 14)


def _fresh_verdict_dict(symbol: str = "MES", rank: int = 11, verdict: str = "PASS") -> dict:
    return {
        "symbol": symbol,
        "family": "trend",
        "rank": rank,
        "verdict": verdict,
        "created_at": datetime.now(_UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Fixtures: fake DO_NOT_TRADE_SYMBOLS
# ---------------------------------------------------------------------------

<<<<<<< HEAD
_FAKE_DNTS = frozenset({"MCL", "MNQ", "M2K"})
=======
_FAKE_DNTS = frozenset({"MGC", "MCL", "MNQ", "M2K"})  # MGC re-added 2026-08-16 (fresh rank4 FAIL)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

# ---------------------------------------------------------------------------
# test_all_pass_returns_green
# ---------------------------------------------------------------------------


def test_all_pass_returns_green(tmp_path):
    """
    When all 7 gates pass, evaluate() returns status=GREEN and pass_count=7.
    """
    days = _make_14_day_window()
    snapshots = _make_snapshots(days, daily_pnl=300.0)
    # Enough wins for 35%+ win rate
    roundtrips = [_make_roundtrip("MES", pnl=50.0, exit_date=d) for d in days[:8]]
    roundtrips += [_make_roundtrip("MES", pnl=-20.0, exit_date=d) for d in days[8:]]
    paper_trades_window: list[dict] = []  # no DNTS violations

    # Patch all data sources + verdict check
    fresh_verdicts = {
        "MES_trend_rank11.json": _fresh_verdict_dict("MES", 11),
        "MGC_trend_rank4.json": _fresh_verdict_dict("MGC", 4),
    }

    with (
        patch("backtest.roi_readiness._load_pnl_snapshots", return_value=snapshots),
        patch("backtest.roi_readiness._load_paper_trades_window", return_value=paper_trades_window),
        patch("backtest.roi_readiness._pair_trades_to_roundtrips", return_value=roundtrips),
        patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path),
        patch("backtest.roi_readiness._fetch_engine_health", return_value={"status": "ok"}),
        # G6 now reads real 5-min health_snapshots via compute_uptime — supply a
        # fully-healthy, sufficiently-sampled window so G6 passes in this scenario.
        patch(
            "scripts.health_uptime.compute_uptime",
            return_value={"polls_total": 2000, "polls_reachable": 2000, "uptime_pct": 100.0},
        ),
    ):
        # Write fresh verdict files so G7 passes
        for fname, vdata in fresh_verdicts.items():
            (tmp_path / fname).write_text(json.dumps(vdata), encoding="utf-8")

        # Also patch the signals import for G5
        with patch.dict(
            "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
        ):
            result = evaluate(_TODAY)

    assert (
        result.status == "GREEN"
    ), f"Expected GREEN, got {result.status}; gates: {[(g.gate_id, g.passed) for g in result.gates]}"
    assert result.pass_count == 7


# ---------------------------------------------------------------------------
# test_5_pass_returns_yellow
# ---------------------------------------------------------------------------


def test_5_pass_returns_yellow(tmp_path):
    """
    When 5 gates pass and 2 fail, status=YELLOW.
    G1 fails (PnL too low) and G2 fails (win rate too low).
    """
    days = _make_14_day_window()
    # G1 fails: avg PnL = $50/day (below $250)
    snapshots = _make_snapshots(days, daily_pnl=50.0)
    # G2 fails: 2/14 wins = 14% (below 35%)
    roundtrips = [_make_roundtrip("MES", pnl=50.0, exit_date=days[0])]
    roundtrips += [_make_roundtrip("MES", pnl=50.0, exit_date=days[1])]
    roundtrips += [_make_roundtrip("MES", pnl=-20.0, exit_date=d) for d in days[2:]]

    paper_trades_window: list[dict] = []
    fresh_verdicts = {
        "MES_trend_rank11.json": _fresh_verdict_dict("MES", 11),
        "MGC_trend_rank4.json": _fresh_verdict_dict("MGC", 4),
    }

    with (
        patch("backtest.roi_readiness._load_pnl_snapshots", return_value=snapshots),
        patch("backtest.roi_readiness._load_paper_trades_window", return_value=paper_trades_window),
        patch("backtest.roi_readiness._pair_trades_to_roundtrips", return_value=roundtrips),
        patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path),
        patch("backtest.roi_readiness._fetch_engine_health", return_value={"status": "ok"}),
        # G6 now reads real 5-min health_snapshots via compute_uptime — supply a
        # fully-healthy, sufficiently-sampled window so G6 passes in this scenario.
        patch(
            "scripts.health_uptime.compute_uptime",
            return_value={"polls_total": 2000, "polls_reachable": 2000, "uptime_pct": 100.0},
        ),
    ):
        for fname, vdata in fresh_verdicts.items():
            (tmp_path / fname).write_text(json.dumps(vdata), encoding="utf-8")
        with patch.dict(
            "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
        ):
            result = evaluate(_TODAY)

    assert result.status == "YELLOW", f"Expected YELLOW, got {result.status}"
    # G1 and G2 should fail
    g1 = next(g for g in result.gates if g.gate_id == "G1")
    g2 = next(g for g in result.gates if g.gate_id == "G2")
    assert not g1.passed, "G1 should fail"
    assert not g2.passed, "G2 should fail"
    assert result.pass_count == 5


# ---------------------------------------------------------------------------
# test_3_pass_returns_red
# ---------------------------------------------------------------------------


def test_3_pass_returns_red(tmp_path):
    """
    When only 3 gates pass, status=RED.
    Fail G1 (pnl), G2 (win rate), G4 (consec loss), G5 (DNTS violation).
    """
    days = _make_14_day_window()
    # G1 fail: avg $0/day
    # G4 fail: 5 consecutive loss days
    loss_snaps: dict[date, dict] = {}
    for i, d in enumerate(days):
        loss_snaps[d] = _make_snapshot(d, daily_pnl=-50.0 if i < 5 else 0.0)

    # G2 fail: 0% win rate (all losses)
    roundtrips = [_make_roundtrip("MES", pnl=-20.0, exit_date=d) for d in days]

    # G5 fail: MCL trade in window
    paper_trades_window = [
        {
            "timestamp": f"{days[0].isoformat()}T15:00:00Z",
            "symbol": "MCL",
            "side": "buy",
            "filled_price": 70.0,
            "trade_value": 70.0,
        }
    ]

    fresh_verdicts = {
        "MES_trend_rank11.json": _fresh_verdict_dict("MES", 11),
        "MGC_trend_rank4.json": _fresh_verdict_dict("MGC", 4),
    }

    with (
        patch("backtest.roi_readiness._load_pnl_snapshots", return_value=loss_snaps),
        patch("backtest.roi_readiness._load_paper_trades_window", return_value=paper_trades_window),
        patch("backtest.roi_readiness._pair_trades_to_roundtrips", return_value=roundtrips),
        patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path),
        patch("backtest.roi_readiness._fetch_engine_health", return_value={"status": "ok"}),
    ):
        for fname, vdata in fresh_verdicts.items():
            (tmp_path / fname).write_text(json.dumps(vdata), encoding="utf-8")
        with patch.dict(
            "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
        ):
            result = evaluate(_TODAY)

    assert result.status == "RED", f"Expected RED, got {result.status}"
    assert result.pass_count <= 4


# ---------------------------------------------------------------------------
# test_consecutive_pass_streak_correctly_counted
# ---------------------------------------------------------------------------


def test_consecutive_pass_streak_correctly_counted(tmp_path):
    """
    A mid-streak failure resets the streak to 0.

    Scenario: last 14 days = 5 passing, 1 failing (G1 pnl low), 8 passing.
    The streak should be 8 (not 13), counting from the most recent consecutive
    block of passing days.
    """
    days = _make_14_day_window()
    # days are in chronological order; last = most recent
    # days[-8:] are all passing (pnl=300), days[-9] is failing (pnl=10),
    # days[:-9] are passing — but streak breaks at days[-9] when walking backward.

    snapshots: dict[date, dict] = {}
    for i, d in enumerate(days):
        if i == len(days) - 9:  # second-to-last block = one failing day
            snapshots[d] = _make_snapshot(d, daily_pnl=10.0)  # G1 fails
        else:
            snapshots[d] = _make_snapshot(d, daily_pnl=300.0)

    # Enough roundtrips for win rate
    roundtrips = [_make_roundtrip("MES", pnl=50.0, exit_date=d) for d in days]

    fresh_verdicts = {
        "MES_trend_rank11.json": _fresh_verdict_dict("MES", 11),
        "MGC_trend_rank4.json": _fresh_verdict_dict("MGC", 4),
    }

    with (
        patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path),
        patch("backtest.roi_readiness._fetch_engine_health", return_value={"status": "ok"}),
        # G6 reads real health_snapshots via compute_uptime — supply a healthy,
        # sufficiently-sampled window so G6 passes on each evaluated day.
        patch(
            "scripts.health_uptime.compute_uptime",
            return_value={"polls_total": 2000, "polls_reachable": 2000, "uptime_pct": 100.0},
        ),
    ):
        for fname, vdata in fresh_verdicts.items():
            (tmp_path / fname).write_text(json.dumps(vdata), encoding="utf-8")
        with patch.dict(
            "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
        ):
            streak = compute_consecutive_passing_days(
                as_of=_TODAY,
                days=days,
                snapshots=snapshots,
                roundtrips=roundtrips,
                paper_trades_window=[],
            )

    # Walk backwards: last 8 days pass, day[-9] fails → streak = 8
    assert streak == 8, f"Expected streak=8 after mid-streak failure, got {streak}"


# ---------------------------------------------------------------------------
# test_zero_donottrade_trades_passes_when_clean
# ---------------------------------------------------------------------------


def test_zero_donottrade_trades_passes_when_clean():
    """G5 passes when there are no trades on DO_NOT_TRADE_SYMBOLS."""
    paper_trades = [
        {
            "timestamp": "2026-05-07T15:00:00Z",
            "symbol": "MES",
            "side": "buy",
            "filled_price": 5300.0,
        },
<<<<<<< HEAD
        {
            "timestamp": "2026-05-07T16:00:00Z",
            "symbol": "MGC",
            "side": "sell",
            "filled_price": 3200.0,
            "pnl": 50.0,
        },
=======
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    ]

    with patch.dict(
        "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
    ):
        result = _eval_g5_no_donottrade(paper_trades)

<<<<<<< HEAD
    assert result.passed, f"G5 should pass with only MES/MGC trades; got: {result.observed}"
=======
    assert result.passed, f"G5 should pass with only MES trades; got: {result.observed}"
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    assert result.gate_id == "G5"


# ---------------------------------------------------------------------------
# test_donottrade_trade_fails_gate
# ---------------------------------------------------------------------------


def test_donottrade_trade_fails_gate():
    """G5 fails when a filled order exists for a DO_NOT_TRADE_SYMBOLS symbol."""
    paper_trades = [
        {
            "timestamp": "2026-05-07T15:00:00Z",
            "symbol": "MNQ",  # blocked
            "side": "buy",
            "filled_price": 19000.0,
            "trade_value": 19000.0,
        }
    ]

    with patch.dict(
        "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
    ):
        result = _eval_g5_no_donottrade(paper_trades)

    assert not result.passed, "G5 should fail when MNQ trade is present"
    assert "MNQ" in result.observed


# ---------------------------------------------------------------------------
# Additional unit tests for individual gates
# ---------------------------------------------------------------------------


def test_g1_passes_at_threshold():
    days = _make_14_day_window()
    snapshots = _make_snapshots(days, daily_pnl=250.0)
    result = _eval_g1_daily_pnl(snapshots, [], days)
    assert result.passed


def test_g1_fails_below_threshold():
    days = _make_14_day_window()
    snapshots = _make_snapshots(days, daily_pnl=249.99)
    result = _eval_g1_daily_pnl(snapshots, [], days)
    assert not result.passed


def test_g2_passes_at_exactly_35_pct():
    days = _make_14_day_window()
    # 35% of 20 trades = 7 wins
    rts = [_make_roundtrip("MES", pnl=50.0)] * 7 + [_make_roundtrip("MES", pnl=-20.0)] * 13
    result = _eval_g2_win_rate(rts)
    assert result.passed


def test_g2_fails_below_35_pct():
    rts = [_make_roundtrip("MES", pnl=50.0)] * 1 + [_make_roundtrip("MES", pnl=-20.0)] * 9
    result = _eval_g2_win_rate(rts)
    # 10%, below 35%
    assert not result.passed


def test_g3_passes_when_no_loss_days():
    days = _make_14_day_window()
    snapshots = _make_snapshots(days, daily_pnl=300.0)
    result = _eval_g3_max_daily_drawdown(snapshots, [], days)
    assert result.passed


def test_g3_fails_when_dd_exceeds_5pct():
    days = _make_14_day_window()
    # One day with equity=10000, loss=600 → 6% dd
    snaps = _make_snapshots(days, daily_pnl=300.0)
    snaps[days[0]] = {
        "daily_pnl": -600.0,
        "portfolio_equity": 10_000.0,
        "peak_equity": 10_000.0,
        "consecutive_losses": 1,
    }
    result = _eval_g3_max_daily_drawdown(snaps, [], days)
    assert not result.passed


def test_g4_passes_with_2_consec_loss_days():
    days = _make_14_day_window()
    snaps = _make_snapshots(days, daily_pnl=300.0)
    snaps[days[0]] = _make_snapshot(days[0], daily_pnl=-50.0)
    snaps[days[1]] = _make_snapshot(days[1], daily_pnl=-50.0)
    result = _eval_g4_consec_loss_days(snaps, [], days)
    assert result.passed


def test_g4_fails_with_4_consec_loss_days():
    days = _make_14_day_window()
    snaps = _make_snapshots(days, daily_pnl=300.0)
    for i in range(4):
        snaps[days[i]] = _make_snapshot(days[i], daily_pnl=-50.0)
    result = _eval_g4_consec_loss_days(snaps, [], days)
    assert not result.passed


def test_g7_passes_with_fresh_verdicts(tmp_path):
    for fname in ["MES_trend_rank11.json", "MGC_trend_rank4.json"]:
        v = _fresh_verdict_dict()
        v["verdict"] = "PASS"
        (tmp_path / fname).write_text(json.dumps(v))

    with patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path):
        result = _eval_g7_verdict_freshness(_TODAY)

    assert result.passed


def test_g7_fails_with_stale_verdict(tmp_path):
    # Anchor to _TODAY (fixed test date) so the age calculation is deterministic
    # regardless of when the test suite is run. TTL_DAYS + 2 gives clear margin.
    today_dt = datetime.combine(_TODAY, datetime.min.time()).replace(tzinfo=_UTC)
    old_ts = (today_dt - timedelta(days=VERDICT_TTL_DAYS + 2)).isoformat()
    for fname in ["MES_trend_rank11.json", "MGC_trend_rank4.json"]:
        v = {"symbol": "MES", "verdict": "PASS", "created_at": old_ts}
        (tmp_path / fname).write_text(json.dumps(v))

    with patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path):
        result = _eval_g7_verdict_freshness(_TODAY)

    assert not result.passed


def test_g7_fails_when_verdict_file_missing(tmp_path):
    # Only write one verdict — MES present, MGC missing
    v = _fresh_verdict_dict("MES", 11)
    (tmp_path / "MES_trend_rank11.json").write_text(json.dumps(v))
    # MGC_trend_rank4.json intentionally absent

    with patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path):
        result = _eval_g7_verdict_freshness(_TODAY)

    assert not result.passed


def test_trading_days_window_excludes_weekends():
    """The 14-day window must contain only Mon-Fri dates."""
    monday = date(2026, 5, 4)  # known Monday
    days = _trading_days_window(monday, 14)
    for d in days:
        assert d.weekday() < 5, f"Weekend day {d} in window"
    assert len(days) == 14


def test_evaluate_does_not_crash_on_empty_data(tmp_path):
    """evaluate() must not raise even with no DB, no trades, no verdicts."""
    with (
        patch("backtest.roi_readiness._DB_PATH", tmp_path / "nonexistent.db"),
        patch("backtest.roi_readiness._PAPER_TRADES_JSON", tmp_path / "nonexistent.json"),
        patch("backtest.roi_readiness._VERDICTS_DIR", tmp_path),
        patch("backtest.roi_readiness._fetch_engine_health", return_value=None),
    ):
        with patch.dict(
            "sys.modules", {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)}
        ):
            result = evaluate(_TODAY)

    assert result.status in ("GREEN", "YELLOW", "RED")
    assert len(result.gates) == 7
    assert result.days_to_live >= 0
