"""Regression coverage for explicit daily P&L scope in portfolio summaries."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from routers import portfolio_router as pr_mod


def test_portfolio_summary_exposes_daily_realized_pnl_explicitly(monkeypatch) -> None:
    orchestrator = MagicMock()

    async def get_portfolio_summary() -> dict[str, object]:
        return {
            "total_daily_pnl": -80.83,
            "daily_target": 500.0,
            "markets": {},
        }

    orchestrator.get_portfolio_summary = get_portfolio_summary
    monkeypatch.setattr(pr_mod, "_get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(pr_mod, "paper_tracker", None)

    summary = asyncio.run(pr_mod.portfolio_summary())

    assert summary["daily_realized_pnl"] == -80.83
    assert summary["realized_pnl"] == -80.83  # backwards-compatible alias
    assert summary["total_daily_pnl"] == -80.83
