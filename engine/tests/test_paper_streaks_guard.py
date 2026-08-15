"""Regression for T1-10 (dashboard-integrity audit): duplicate/shadowed
``/paper/streaks`` route registrations in ``routers/portfolio_router.py``.

Before the fix, ``/paper/streaks`` was registered TWICE with diverging
response shapes (one without ``streak_history``, one with it). FastAPI
resolves the FIRST-registered route for a given path, so the earlier,
poorer-shaped handler silently shadowed the later one that the dashboard's
``StreakTrackerWidget`` actually expects (see ``StreaksResponse`` in
``dashboard/lib/api.ts``, which requires ``streak_history``). The shadowed
handler also had no sample-size guard, so a single lucky trade could render
as a confident "streak" badge.

The fix consolidates the route to the single implementation that matches the
dashboard's contract, and adds a ``trades >= 2`` sample-size guard (mirroring
the existing ``eligible = [... trades >= 2]`` gate used for best/worst hour
in ``paper_hourly_stats``) so fewer than 2 closed trades cannot be reported
as a meaningful streak.

A third, differently-shaped endpoint at ``/stats/streaks``
(``get_trading_streaks``) is intentionally left alone: it lives on a
distinct path (no shadowing possible) and is not called anywhere in
``dashboard/`` (verified via grep) as of this fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routers import portfolio_router as pr_mod  # noqa: E402


class _FakeTracker:
    """Minimal stand-in for PortfolioTracker exposing only get_trade_history."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_trade_history(self, limit: int = 5000) -> list[dict]:  # noqa: ARG002
        return self._rows


def _closed_trade(pnl: float, exit_time: str) -> dict:
    return {
        "is_open": False,
        "exit_time": exit_time,
        "pnl": pnl,
    }


def test_no_duplicate_paper_streaks_route_registration():
    """Pin the consolidation: exactly one route serves /paper/streaks.

    Regression guard against re-introducing a shadowing duplicate — before
    the fix, this path was registered twice on ``pr_mod.router``.
    """
    matches = [
        route
        for route in pr_mod.router.routes
        if getattr(route, "path", None) == "/paper/streaks"
    ]
    assert len(matches) == 1, (
        f"expected exactly one /paper/streaks route registration, found {len(matches)}"
    )
    assert matches[0].endpoint.__name__ == "paper_streaks"
    # The old shadowing duplicate must be gone entirely, not just unreachable.
    assert not hasattr(pr_mod, "get_streaks")


async def test_fewer_than_two_trades_returns_neutral_streak():
    """The guarded behavior: 0 or 1 closed trades cannot establish a streak."""
    old_pt = pr_mod.paper_tracker
    try:
        # Zero closed trades.
        pr_mod.paper_tracker = _FakeTracker([])
        out = await pr_mod.paper_streaks()
        assert out["current_streak"] == {"type": "NONE", "count": 0}
        assert out["max_win_streak"] == 0
        assert out["max_loss_streak"] == 0
        assert out["streak_history"] == []
        assert out["total_trades"] == 0

        # Exactly one closed trade (a win) — must NOT render as a confident
        # "WIN STREAK: 1" / 100%-style badge off a single sample.
        pr_mod.paper_tracker = _FakeTracker(
            [_closed_trade(pnl=150.0, exit_time="2026-07-01T14:30:00Z")]
        )
        out = await pr_mod.paper_streaks()
        assert out["current_streak"] == {"type": "NONE", "count": 0}
        assert out["max_win_streak"] == 0
        assert out["max_loss_streak"] == 0
        assert out["streak_history"] == []
        # Honest count is preserved even though the streak fields are guarded.
        assert out["total_trades"] == 1
    finally:
        pr_mod.paper_tracker = old_pt


async def test_two_or_more_trades_lifts_the_guard():
    """Once the sample size is >= 2, real streak data is reported."""
    old_pt = pr_mod.paper_tracker
    try:
        pr_mod.paper_tracker = _FakeTracker(
            [
                _closed_trade(pnl=100.0, exit_time="2026-07-01T14:00:00Z"),
                _closed_trade(pnl=50.0, exit_time="2026-07-02T14:00:00Z"),
            ]
        )
        out = await pr_mod.paper_streaks()
        assert out["current_streak"] == {"type": "WIN", "count": 2}
        assert out["max_win_streak"] == 2
        assert out["max_loss_streak"] == 0
        assert out["total_trades"] == 2
        assert len(out["streak_history"]) == 1
        assert out["streak_history"][0]["type"] == "WIN"
        assert out["streak_history"][0]["count"] == 2
    finally:
        pr_mod.paper_tracker = old_pt


def test_paper_streaks_endpoint_contract_via_http():
    """End-to-end through the actual FastAPI route (not just the function),
    proving the guard fires on the reachable /portfolio/paper/streaks path."""
    old_pt, old_db, old_safety = (
        pr_mod.paper_tracker,
        pr_mod.db_manager,
        pr_mod._safety_layer,
    )
    try:
        pr_mod.paper_tracker = _FakeTracker(
            [_closed_trade(pnl=150.0, exit_time="2026-07-01T14:30:00Z")]
        )
        app = FastAPI()
        app.include_router(pr_mod.router, prefix="/portfolio")
        client = TestClient(app)

        resp = client.get("/portfolio/paper/streaks")
        assert resp.status_code == 200
        body = resp.json()
        # Response shape matches dashboard's StreaksResponse contract
        # (streak_history present) — the pre-fix shadowing duplicate omitted
        # this key entirely.
        assert "streak_history" in body
        assert body["current_streak"] == {"type": "NONE", "count": 0}
        assert body["total_trades"] == 1
    finally:
        pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer = (
            old_pt,
            old_db,
            old_safety,
        )
