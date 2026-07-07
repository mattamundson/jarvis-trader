"""
Regression — ROI-readiness G6 uptime gate must not false-green.

The old G6 counted "a pnl_snapshots row exists for the day" as uptime, so it
could score 95%+ even if the engine was up only minutes/day. The fix reads the
real 5-minute health_snapshots via scripts.health_uptime.compute_uptime() and,
when that data is too sparse, reports insufficient granularity instead of a
misleading pass.
"""

from __future__ import annotations

from datetime import date, timedelta

import backtest.roi_readiness as roi


def _days(n: int = 14) -> list[date]:
    base = date(2026, 1, 5)
    return [base + timedelta(days=i) for i in range(n)]


def test_g6_insufficient_granularity_does_not_pass(monkeypatch):
    # health_snapshots barely populated → cannot verify uptime → must NOT pass,
    # even though the reported uptime_pct looks perfect.
    monkeypatch.setattr(
        "scripts.health_uptime.compute_uptime",
        lambda *a, **k: {"polls_total": 3, "polls_reachable": 3, "uptime_pct": 100.0},
    )
    res = roi._eval_g6_engine_uptime({}, _days(14))
    assert res.passed is False
    assert "insufficient granularity" in res.observed


def test_g6_high_uptime_passes(monkeypatch):
    monkeypatch.setattr(
        "scripts.health_uptime.compute_uptime",
        lambda *a, **k: {"polls_total": 1000, "polls_reachable": 980, "uptime_pct": 98.0},
    )
    res = roi._eval_g6_engine_uptime({}, _days(14))
    assert res.passed is True
    assert "98.0%" in res.observed


def test_g6_low_uptime_fails_despite_full_snapshot_proxy(monkeypatch):
    # The false-green case: a pnl_snapshots row exists EVERY day (the old proxy
    # would report 100%), but the engine was actually reachable only 40% of the
    # 5-min health polls. The corrected gate fails.
    monkeypatch.setattr(
        "scripts.health_uptime.compute_uptime",
        lambda *a, **k: {"polls_total": 1000, "polls_reachable": 400, "uptime_pct": 40.0},
    )
    full_proxy = {d: {} for d in _days(14)}
    res = roi._eval_g6_engine_uptime(full_proxy, _days(14))
    assert res.passed is False
    assert "40.0%" in res.observed


def test_g6_empty_window_does_not_pass():
    res = roi._eval_g6_engine_uptime({}, [])
    assert res.passed is False
