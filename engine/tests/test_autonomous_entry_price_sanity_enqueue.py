"""Enqueue-time ENTRY_PRICE_SANITY in autonomous_tick.

The check used to log only on reject or raise, so a passing check was
indistinguishable from a skipped one in prod logs. These tests pin that it
runs with the verdict's entry price and the injected data_manager, logs a
pass line, and blocks the enqueue on reject or on an exception (fail-closed).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import scheduler.pipeline_autonomous as pa
from scheduler.pipeline_autonomous import (
    _FLAG_NAME,
    _ensure_table,
    autonomous_tick,
    inject_autonomous_deps,
)

_ENTRY = 2100.50
_ENV = {
    _FLAG_NAME: "1",
    "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL",
    "AUTONOMOUS_CONFIDENCE_THRESHOLD": "0.65",
    "AUTONOMOUS_CANDIDATE_TTL_SECONDS": "1800",
}


def _count_pending(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM pipeline_approval_queue WHERE status='pending'"
        ).fetchone()
    return row[0] if row else 0


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "autonomous_sanity.db")
    _ensure_table(path)
    pipeline = MagicMock()
    pipeline.analyze_and_decide = AsyncMock(
        return_value={
            "final_action": "buy",
            "fund_decision": {"final_conviction": 0.82},
            "trade_decision": {"confidence": 0.82, "entry_price": _ENTRY, "limit_price": _ENTRY},
        }
    )
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    data_manager = SimpleNamespace(ibkr=SimpleNamespace(is_connected=True))
    inject_autonomous_deps(pipeline, safety, path, data_manager=data_manager)
    return path


async def _tick(check: AsyncMock, caplog) -> dict:
    with (
        patch.dict(os.environ, _ENV),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=False),
        patch("risk.entry_price_sanity.is_entry_price_sanity_enabled", return_value=True),
        patch("risk.entry_price_sanity.check_entry_price_sanity", check),
        caplog.at_level(logging.INFO, logger=pa.logger.name),
    ):
        return await autonomous_tick()


@pytest.mark.asyncio
async def test_sanity_pass_runs_logs_and_enqueues(db_path, caplog) -> None:
    check = AsyncMock(return_value=(True, "ok"))

    result = await _tick(check, caplog)

    check.assert_awaited_once()
    kwargs = check.await_args.kwargs
    assert kwargs["symbol"] == "MCL"
    assert kwargs["entry_price"] == pytest.approx(_ENTRY)
    assert kwargs["data_manager"] is pa._data_manager
    assert "[ENTRY_PRICE_SANITY] MCL entry=2100.5 passed" in caplog.text
    assert len(result["enqueued"]) == 1
    assert _count_pending(db_path) == 1


@pytest.mark.asyncio
async def test_sanity_reject_blocks_enqueue(db_path, caplog) -> None:
    check = AsyncMock(return_value=(False, "entry 2100.5 is 40 ATR from last"))

    result = await _tick(check, caplog)

    assert result["enqueued"] == []
    assert any("entry_price_sanity:" in e["error"] for e in result["errors"])
    assert "passed" not in caplog.text
    assert _count_pending(db_path) == 0


@pytest.mark.asyncio
async def test_sanity_exception_fails_closed(db_path, caplog) -> None:
    check = AsyncMock(side_effect=RuntimeError("no quote"))

    result = await _tick(check, caplog)

    assert result["enqueued"] == []
    assert any("entry_price_sanity_error:" in e["error"] for e in result["errors"])
    assert _count_pending(db_path) == 0
