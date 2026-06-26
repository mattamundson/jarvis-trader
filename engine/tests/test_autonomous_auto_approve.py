"""
Tests for the opt-in paper-only auto-approve hook in the autonomous scheduler.

Behavior contract (engine/scheduler/pipeline_autonomous.py):
  _maybe_auto_approve_paper(candidate_id) ->
    * flag OFF                       -> returns False, approve_candidate NOT called
    * flag ON  + LIVE enabled        -> returns False, approve_candidate NOT called (live-safe)
    * flag ON  + paper (LIVE off)    -> returns True,  approve_candidate awaited once with candidate_id
    * flag ON  + paper + approve raises -> returns True (exception swallowed, tick loop survives)

The hook NEVER auto-approves when LIVE_TRADING_ENABLED is True — the autonomous
path's documented "never auto-submit for live" guarantee must hold.
"""

from unittest.mock import AsyncMock

import pytest

import scheduler.pipeline_autonomous as pa


@pytest.fixture
def _patch_approve(monkeypatch):
    """Replace routers.approval_queue_router.approve_candidate with an AsyncMock."""
    import routers.approval_queue_router as aqr

    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(aqr, "approve_candidate", mock)
    return mock


@pytest.mark.asyncio
async def test_flag_off_does_not_approve(monkeypatch, _patch_approve):
    monkeypatch.delenv(pa._AUTO_APPROVE_PAPER_NAME, raising=False)
    monkeypatch.setattr(pa, "_get_live_trading_enabled", lambda: False)

    result = await pa._maybe_auto_approve_paper(123)

    assert result is False
    _patch_approve.assert_not_called()


@pytest.mark.asyncio
async def test_flag_on_but_live_refuses(monkeypatch, _patch_approve):
    monkeypatch.setenv(pa._AUTO_APPROVE_PAPER_NAME, "1")
    monkeypatch.setattr(pa, "_get_live_trading_enabled", lambda: True)

    result = await pa._maybe_auto_approve_paper(456)

    assert result is False
    _patch_approve.assert_not_called()


@pytest.mark.asyncio
async def test_flag_on_paper_approves_once(monkeypatch, _patch_approve):
    monkeypatch.setenv(pa._AUTO_APPROVE_PAPER_NAME, "1")
    monkeypatch.setattr(pa, "_get_live_trading_enabled", lambda: False)

    result = await pa._maybe_auto_approve_paper(789)

    assert result is True
    _patch_approve.assert_awaited_once_with(789)


@pytest.mark.asyncio
async def test_approve_exception_is_swallowed(monkeypatch, _patch_approve):
    monkeypatch.setenv(pa._AUTO_APPROVE_PAPER_NAME, "1")
    monkeypatch.setattr(pa, "_get_live_trading_enabled", lambda: False)
    _patch_approve.side_effect = RuntimeError("submit failed")

    # Must not raise — the tick loop has to survive a single bad approval.
    result = await pa._maybe_auto_approve_paper(999)

    assert result is True
    _patch_approve.assert_awaited_once_with(999)


@pytest.mark.parametrize(
    "val,expected",
    [("1", True), ("true", True), ("yes", True), ("0", False), ("", False), ("off", False)],
)
def test_auto_approve_paper_enabled_parsing(monkeypatch, val, expected):
    monkeypatch.setenv(pa._AUTO_APPROVE_PAPER_NAME, val)
    assert pa._auto_approve_paper_enabled() is expected
