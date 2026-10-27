"""
Tests for engine/scheduler/pipeline_autonomous.py

Covers:
  - test_autonomous_tick_disabled_by_default
  - test_autonomous_tick_refuses_on_kill_switch
  - test_autonomous_tick_refuses_on_live_trading_enabled
  - test_autonomous_tick_enqueues_on_green_verdict
  - test_autonomous_tick_skips_low_confidence
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scheduler.pipeline_autonomous import (
    _FLAG_NAME,
    _ensure_table,
    _has_pending_candidate,
    autonomous_tick,
    inject_autonomous_deps,
    is_autonomous_enabled,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "autonomous_test.db")
    _ensure_table(db_path)
    return db_path


def _count_pending(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM pipeline_approval_queue WHERE status='pending'"
        ).fetchone()
    return row[0] if row else 0


def _make_hold_result() -> dict:
    return {
        "final_action": "hold",
        "fund_decision": {"final_conviction": 0.30},
        "trade_decision": {"confidence": 0.30},
    }


def _make_green_result(action: str = "buy", confidence: float = 0.80) -> dict:
    return {
        "final_action": action,
        "fund_decision": {"final_conviction": confidence},
        "trade_decision": {
            "confidence": confidence,
            "entry_price": 2100.50,
            "limit_price": 2100.50,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_autonomous_tick_disabled_by_default() -> None:
    """is_autonomous_enabled() returns False when env var absent."""
    # Remove flag from env if set
    env = {k: v for k, v in os.environ.items() if k != _FLAG_NAME}
    with patch.dict(os.environ, env, clear=True):
        assert is_autonomous_enabled() is False


@pytest.mark.asyncio
async def test_autonomous_tick_no_op_when_flag_off(tmp_path: Path) -> None:
    """autonomous_tick returns immediately without touching DB when flag=0."""
    db_path = _fresh_db(tmp_path)

    mock_pipeline = AsyncMock()
    mock_safety = MagicMock()
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)

    with patch.dict(os.environ, {_FLAG_NAME: "0"}):
        result = await autonomous_tick()

    assert result["enabled"] is False
    assert result["enqueued"] == []
    mock_pipeline.analyze_and_decide.assert_not_called()
    assert _count_pending(db_path) == 0


@pytest.mark.asyncio
async def test_autonomous_tick_refuses_on_kill_switch(tmp_path: Path) -> None:
    """When kill switch is active, tick refuses to enqueue any candidate."""
    db_path = _fresh_db(tmp_path)

    mock_pipeline = AsyncMock()
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": True}
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)

    with (
        patch.dict(os.environ, {_FLAG_NAME: "1", "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL"}),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=False),
    ):
        result = await autonomous_tick()

    assert "refused_reason" in result
    assert "kill switch" in result["refused_reason"].lower()
    assert _count_pending(db_path) == 0
    mock_pipeline.analyze_and_decide.assert_not_called()


@pytest.mark.asyncio
async def test_autonomous_tick_refuses_on_live_trading_enabled(tmp_path: Path) -> None:
    """Paranoid check: if LIVE_TRADING_ENABLED=True, tick must refuse."""
    db_path = _fresh_db(tmp_path)

    mock_pipeline = AsyncMock()
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)

    with (
        patch.dict(os.environ, {_FLAG_NAME: "1", "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL"}),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=True),
    ):
        result = await autonomous_tick()

    assert "refused_reason" in result
    reason = result["refused_reason"].lower()
    assert "live" in reason or "live_trading" in reason.upper()
    assert _count_pending(db_path) == 0
    mock_pipeline.analyze_and_decide.assert_not_called()


@pytest.mark.asyncio
async def test_autonomous_tick_enqueues_on_green_verdict(tmp_path: Path) -> None:
    """
    When flag=1, kill-switch off, live-trading off, and pipeline returns high-confidence
    BUY, autonomous_tick inserts exactly one row in pipeline_approval_queue.
    """
    db_path = _fresh_db(tmp_path)

    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(return_value=_make_green_result("buy", 0.82))
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)

    with (
        patch.dict(
            os.environ,
            {
                _FLAG_NAME: "1",
                "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL",
                "AUTONOMOUS_CONFIDENCE_THRESHOLD": "0.65",
                "AUTONOMOUS_CANDIDATE_TTL_SECONDS": "1800",
            },
        ),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=False),
    ):
        result = await autonomous_tick()

    assert len(result["enqueued"]) == 1
    assert result["enqueued"][0]["symbol"] == "MCL"
    assert result["enqueued"][0]["direction"] == "LONG"
    assert result["enqueued"][0]["confidence"] == pytest.approx(0.82, abs=0.01)
    assert _count_pending(db_path) == 1


@pytest.mark.asyncio
async def test_autonomous_tick_skips_low_confidence(tmp_path: Path) -> None:
    """Pipeline returns BUY but confidence < threshold → no enqueue."""
    db_path = _fresh_db(tmp_path)

    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(
        return_value=_make_green_result("buy", confidence=0.40)
    )
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)

    with (
        patch.dict(
            os.environ,
            {
                _FLAG_NAME: "1",
                "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL",
                "AUTONOMOUS_CONFIDENCE_THRESHOLD": "0.65",
            },
        ),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=False),
    ):
        result = await autonomous_tick()

    assert len(result["enqueued"]) == 0
    assert len(result["skipped_low_confidence"]) == 1
    assert _count_pending(db_path) == 0


async def _run_tick_with(result_dict: dict, tmp_path: Path) -> tuple[dict, str]:
    db_path = _fresh_db(tmp_path)
    mock_pipeline = MagicMock()
    mock_pipeline.analyze_and_decide = AsyncMock(return_value=result_dict)
    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    inject_autonomous_deps(mock_pipeline, mock_safety, db_path)
    with (
        patch.dict(
            os.environ,
            {
                _FLAG_NAME: "1",
                "AUTONOMOUS_ACTIVE_SYMBOLS": "MCL",
                "AUTONOMOUS_CONFIDENCE_THRESHOLD": "0.65",
            },
        ),
        patch("scheduler.pipeline_autonomous._get_live_trading_enabled", return_value=False),
    ):
        return await autonomous_tick(), db_path


@pytest.mark.asyncio
async def test_autonomous_tick_gates_on_boosted_confidence(tmp_path: Path) -> None:
    """2026-10-26 candidates 920/922: raw 0.75 passed the 0.65 tick gate while the
    pipeline's scored (boosted) confidence was 0.64. The tick must gate on boosted."""
    res = _make_green_result("buy", confidence=0.75)
    res["boosted_confidence"] = 0.64

    result, db_path = await _run_tick_with(res, tmp_path)

    assert len(result["enqueued"]) == 0
    assert len(result["skipped_low_confidence"]) == 1
    assert result["skipped_low_confidence"][0]["confidence"] == pytest.approx(0.64)
    assert _count_pending(db_path) == 0


@pytest.mark.asyncio
async def test_autonomous_tick_enqueues_when_boosted_above_threshold(tmp_path: Path) -> None:
    res = _make_green_result("buy", confidence=0.60)
    res["boosted_confidence"] = 0.70

    result, db_path = await _run_tick_with(res, tmp_path)

    assert len(result["enqueued"]) == 1
    assert result["enqueued"][0]["confidence"] == pytest.approx(0.70, abs=0.01)
    assert _count_pending(db_path) == 1


@pytest.mark.asyncio
async def test_autonomous_tick_falls_back_when_boosted_absent(tmp_path: Path) -> None:
    """No boosted_confidence (e.g. older pipeline path): keep the previous fallback."""
    result, _ = await _run_tick_with(_make_green_result("buy", confidence=0.82), tmp_path)

    assert len(result["enqueued"]) == 1
    assert result["enqueued"][0]["confidence"] == pytest.approx(0.82, abs=0.01)
