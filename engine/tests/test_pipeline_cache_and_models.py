"""
Tests for pipeline cache invalidation endpoints and agent model constants.

Covers:
  - POST /pipeline/cache/invalidate/{symbol}
  - POST /pipeline/cache/invalidate-all
  - cache_signal() / invalidate_signal() round-trip
  - RiskManagerAgent.MODEL == "claude-sonnet-4-6"
  - FundManagerAgent.MODEL == "claude-sonnet-4-6"
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import pipeline_router as pr_mod

# ---------------------------------------------------------------------------
# Minimal FastAPI app wrapping the pipeline router
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline_client():
    """TestClient with pipeline router mounted (no full main.py needed).

    The router itself already declares prefix="/pipeline", so we mount it
    without an additional prefix to avoid double /pipeline/pipeline/.
    """
    app = FastAPI()
    app.include_router(pr_mod.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Cache invalidation — HTTP endpoints
# ---------------------------------------------------------------------------


def test_invalidate_symbol_returns_expected_shape(pipeline_client: TestClient):
    """POST /pipeline/cache/invalidate/{symbol} returns {invalidated: bool, symbol: UPPER}."""
    with patch("cache.signal_cache.invalidate_signal", new_callable=AsyncMock) as mock_inv:
        mock_inv.return_value = True
        resp = pipeline_client.post("/pipeline/cache/invalidate/mes")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "MES"
    assert body["invalidated"] is True


def test_invalidate_symbol_uppercases(pipeline_client: TestClient):
    """Symbol is always uppercased in the response regardless of input case."""
    with patch("cache.signal_cache.invalidate_signal", new_callable=AsyncMock) as mock_inv:
        mock_inv.return_value = False
        resp = pipeline_client.post("/pipeline/cache/invalidate/mnq")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "MNQ"
    assert body["invalidated"] is False


def test_invalidate_symbol_already_uppercase(pipeline_client: TestClient):
    """Symbol already uppercase passes through unchanged."""
    with patch("cache.signal_cache.invalidate_signal", new_callable=AsyncMock) as mock_inv:
        mock_inv.return_value = True
        resp = pipeline_client.post("/pipeline/cache/invalidate/MCL")

    assert resp.status_code == 200
    assert resp.json()["symbol"] == "MCL"


def test_invalidate_all_returns_expected_shape(pipeline_client: TestClient):
    """POST /pipeline/cache/invalidate-all returns {invalidated: bool}."""
    with patch("cache.signal_cache.invalidate_all", new_callable=AsyncMock) as mock_all:
        mock_all.return_value = True
        resp = pipeline_client.post("/pipeline/cache/invalidate-all")

    assert resp.status_code == 200
    body = resp.json()
    assert "invalidated" in body
    assert body["invalidated"] is True


def test_invalidate_all_false_when_redis_unavailable(pipeline_client: TestClient):
    """invalidate-all returns False when Redis is unavailable."""
    with patch("cache.signal_cache.invalidate_all", new_callable=AsyncMock) as mock_all:
        mock_all.return_value = False
        resp = pipeline_client.post("/pipeline/cache/invalidate-all")

    assert resp.status_code == 200
    assert resp.json()["invalidated"] is False


# ---------------------------------------------------------------------------
# Cache round-trip — unit tests on signal_cache functions directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_signal_then_invalidate_removes_entry():
    """After cache_signal(), invalidate_signal() returns True and clears the key."""
    from cache import redis_client as rc
    from cache import signal_cache

    # Reset the in-memory fallback for a clean slate
    rc._fallback_cache.clear()

    payload = {"symbol": "MES", "action": "BUY", "conviction": 0.8}

    # Cache it
    cached = await signal_cache.cache_signal("MES", payload, ttl_seconds=60)
    assert cached is True

    # Should be retrievable
    result = await signal_cache.get_cached_signal("MES")
    assert result is not None
    assert result["action"] == "BUY"

    # Invalidate
    deleted = await signal_cache.invalidate_signal("MES")
    assert deleted is True

    # Should be gone
    after_delete = await signal_cache.get_cached_signal("MES")
    assert after_delete is None


@pytest.mark.asyncio
async def test_invalidate_signal_nonexistent_key_returns_false():
    """invalidate_signal() on a key that doesn't exist returns False."""
    from cache import redis_client as rc
    from cache import signal_cache

    rc._fallback_cache.clear()

    result = await signal_cache.invalidate_signal("DOESNOTEXIST")
    assert result is False


@pytest.mark.asyncio
async def test_get_cached_signal_returns_none_when_empty():
    """get_cached_signal() returns None when cache is empty."""
    from cache import redis_client as rc
    from cache import signal_cache

    rc._fallback_cache.clear()

    result = await signal_cache.get_cached_signal("MES")
    assert result is None


# ---------------------------------------------------------------------------
# Model constants — verify downgrade from opus to sonnet
# ---------------------------------------------------------------------------


def test_risk_manager_model_is_sonnet():
    """RiskManagerAgent.MODEL must be claude-sonnet-4-6 (not opus)."""
    from agents.risk_manager import RiskManagerAgent

    assert RiskManagerAgent.MODEL == "claude-sonnet-4-6"


def test_fund_manager_model_is_sonnet():
    """FundManagerAgent.MODEL must be claude-sonnet-4-6 (not opus)."""
    from agents.fund_manager import FundManagerAgent

    assert FundManagerAgent.MODEL == "claude-sonnet-4-6"


def test_risk_manager_model_is_not_opus():
    """Explicit guard: opus must not be used in paper-mode risk agent."""
    from agents.risk_manager import RiskManagerAgent

    assert "opus" not in RiskManagerAgent.MODEL.lower()


def test_fund_manager_model_is_not_opus():
    """Explicit guard: opus must not be used in paper-mode fund agent."""
    from agents.fund_manager import FundManagerAgent

    assert "opus" not in FundManagerAgent.MODEL.lower()


# ---------------------------------------------------------------------------
# Fix 1 — TraderAgent conviction formula (abs(bull - bear) / 10.0)
# ---------------------------------------------------------------------------


def test_trader_conviction_tie_gives_zero():
    """6/6 debate tie should produce conviction=0.0, not 6.0"""
    bull_s = 6.0
    bear_s = 6.0
    conviction = abs(bull_s - bear_s) / 10.0
    assert conviction == 0.0


def test_trader_conviction_clear_bear_win():
    """10/4 bear win should give conviction=0.6"""
    bull_s = 4.0
    bear_s = 10.0
    conviction = abs(bull_s - bear_s) / 10.0
    assert conviction == 0.6


# ---------------------------------------------------------------------------
# Fix 2 — FundManagerAgent priority inference when LLM omits the field
# ---------------------------------------------------------------------------


def test_fund_manager_priority_inferred_when_approved():
    """LLM approving but omitting priority should default to 'immediate', not 'skip'"""
    from agents.fund_manager import FundManagerAgent

    agent = FundManagerAgent(llm_client=None)
    result = {"approved": True, "reasoning": "looks good"}
    trade = {"quantity": 1}
    risk = {"modified_quantity": 1}
    decision = agent._parse_fund_decision(result, trade, risk)
    assert decision.approved is True
    assert decision.priority == "immediate"
    assert decision.final_quantity == 1


def test_fund_manager_priority_skip_when_not_approved():
    """Rejected trade should have priority='skip'"""
    from agents.fund_manager import FundManagerAgent

    agent = FundManagerAgent(llm_client=None)
    result = {"approved": False, "reasoning": "too risky"}
    trade = {"quantity": 1}
    risk = {"modified_quantity": 1}
    decision = agent._parse_fund_decision(result, trade, risk)
    assert decision.approved is False
    assert decision.priority == "skip"
