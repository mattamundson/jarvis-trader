"""Regression tests for /pipeline/actionable route fail-open behavior."""

from __future__ import annotations

import pytest

from routers import actionable_router


class _FakeDb:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def get_recent_approvals_all_statuses(self, limit: int = 10) -> list[dict]:
        return self.rows[:limit]


@pytest.mark.asyncio
async def test_actionable_route_skips_price_fetch_for_rejected_rows(monkeypatch):
    """Rejected rows should produce raw_count diagnostics without broker/cache IO."""

    actionable_router.inject_dependencies(
        _FakeDb(
            [
                {
                    "approval_id": "rejected-1",
                    "symbol": "MES",
                    "action": "buy",
                    "status": "rejected",
                    "quantity": 1,
                    "entry_price": 7780.75,
                    "created_at": "2026-08-11T16:03:24",
                    "pipeline_snapshot": {"trade_decision": {"entry_price": 7780.75}},
                }
            ]
        )
    )

    async def _boom(_symbols: str) -> dict:
        raise AssertionError("price snapshot should not be called for rejected rows")

    import routers.prices_router as prices_router

    monkeypatch.setattr(prices_router, "get_price_snapshot", _boom)

    board = await actionable_router.get_actionable_board(limit=25)

    assert board["available"] is True
    assert board["items"] == []
    assert board["count"] == 0
    assert board["raw_count"] == 1
    assert board["shown"] == 0


@pytest.mark.asyncio
async def test_actionable_route_fails_open_when_recent_read_fails():
    class BrokenDb:
        def get_recent_approvals_all_statuses(self, limit: int = 10) -> list[dict]:
            raise RuntimeError("locked")

    actionable_router.inject_dependencies(BrokenDb())

    board = await actionable_router.get_actionable_board(limit=25)

    assert board["available"] is False
    assert board["items"] == []
    assert board["count"] == 0
    assert "Approvals read failed" in board["note"]
